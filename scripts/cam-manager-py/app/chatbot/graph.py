"""
LangGraph Chatbot with Claude
Streaming chat with tool support (tools loaded from config)
"""
import os
from typing import Annotated, TypedDict, Sequence, AsyncGenerator, Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """State for the chatbot graph"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tools: list[Any]  # Tools will be added from config


# System prompt for Falcon-Eye assistant
SYSTEM_PROMPT = """You are Falcon-Eye Assistant, an AI helper for the Falcon-Eye camera management system.

You have access to tools that let you check:
- Camera statuses and details
- Cluster node information  
- System settings and health

You can help users with:
- Checking camera statuses ("How are my cameras doing?")
- Getting camera details ("Tell me about the office camera")
- Viewing cluster health ("Is everything running?")
- Understanding system settings
- Troubleshooting camera issues
- Explaining system features

Use your tools when users ask about cameras, nodes, or system status.
Be concise, helpful, and friendly. Format responses nicely with markdown.
"""


def get_llm(streaming: bool = True) -> ChatAnthropic:
    """Get Claude LLM instance"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    return ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=api_key,
        streaming=streaming,
        max_tokens=1024,
    )


def create_graph(tools: list = None):
    """Create the LangGraph chatbot graph"""
    
    async def chat_node(state: ChatState) -> ChatState:
        """Main chat node - calls Claude"""
        llm = get_llm(streaming=False)
        
        # Add system message if not present
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=SYSTEM_PROMPT))
        
        # Bind tools if available
        if state.get("tools"):
            llm = llm.bind_tools(state["tools"])
        
        response = await llm.ainvoke(messages)
        return {"messages": [response]}
    
    # Build graph
    workflow = StateGraph(ChatState)
    workflow.add_node("chat", chat_node)
    workflow.set_entry_point("chat")
    workflow.add_edge("chat", END)
    
    return workflow.compile()


def get_enabled_tools_from_config() -> list:
    """Load enabled tools from config"""
    from app.chatbot.tools import get_enabled_tools, DEFAULT_TOOLS
    
    # Try to get enabled tools from ConfigMap
    enabled_tool_names = DEFAULT_TOOLS
    
    try:
        from app.services.k8s import core_api
        from app.config import get_settings
        settings = get_settings()
        
        cm = core_api.read_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace
        )
        if cm.data and cm.data.get("CHATBOT_TOOLS"):
            enabled_tool_names = [t.strip() for t in cm.data.get("CHATBOT_TOOLS", "").split(",") if t.strip()]
    except Exception:
        pass  # Use defaults
    
    return get_enabled_tools(enabled_tool_names)


async def stream_chat(
    messages: list[dict],
    tools: list = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    Stream chat responses from Claude with tool support.
    Yields tuples of (event_type, data):
      - ("text", "token") - text content to display
      - ("thinking", "") - tools are being executed (show loading)
    """
    llm = get_llm(streaming=True)
    
    # Load tools from config if not provided
    if tools is None:
        tools = get_enabled_tools_from_config()
    
    # Convert dict messages to LangChain messages
    lc_messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
    
    # Bind tools if available
    if tools:
        llm = llm.bind_tools(tools)
    
    def extract_text(content) -> str:
        """Extract text from content (string or list of blocks)"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Extract text from content blocks
            texts = []
            for block in content:
                if isinstance(block, str):
                    texts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "".join(texts)
        return ""
    
    # Stream the response - collect chunks to check for tool calls
    collected_text = []
    tool_calls = []
    has_tool_calls = False
    
    async for chunk in llm.astream(lc_messages):
        # Collect tool calls (they come in the stream too)
        if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
            has_tool_calls = True
            for tc in chunk.tool_call_chunks:
                # Build up tool calls from chunks
                if tc.get("index") is not None:
                    idx = tc["index"]
                    while len(tool_calls) <= idx:
                        tool_calls.append({"name": "", "args": "", "id": ""})
                    if tc.get("name"):
                        tool_calls[idx]["name"] = tc["name"]
                    if tc.get("args"):
                        tool_calls[idx]["args"] += tc["args"]
                    if tc.get("id"):
                        tool_calls[idx]["id"] = tc["id"]
        
        # Collect text (but don't stream if we're going to use tools)
        if hasattr(chunk, "content") and chunk.content:
            text = extract_text(chunk.content)
            if text:
                collected_text.append(text)
                # Only stream immediately if no tool calls detected yet
                if not has_tool_calls:
                    yield ("text", text)
    
    # If there were tool calls, execute them and stream the follow-up
    if tool_calls and any(tc["name"] for tc in tool_calls):
        # Emit thinking event so UI shows loading
        yield ("thinking", "")
        
        tool_results = []
        tools_by_name = {t.name: t for t in tools} if tools else {}
        
        # Build the AI message with tool calls for history
        ai_message_content = "".join(collected_text)
        ai_tool_calls = [
            {"name": tc["name"], "args": tc["args"], "id": tc["id"]}
            for tc in tool_calls if tc["name"]
        ]
        
        # Parse args from string to dict
        import json as json_module
        for tc in ai_tool_calls:
            if isinstance(tc["args"], str):
                try:
                    tc["args"] = json_module.loads(tc["args"]) if tc["args"] else {}
                except:
                    tc["args"] = {}
        
        # Create AI message with tool calls
        ai_msg = AIMessage(content=ai_message_content, tool_calls=ai_tool_calls)
        
        # Execute each tool
        for tc in ai_tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            
            print(f"[Chatbot] Executing tool: {tool_name} with args: {tool_args}")
            
            if tool_name in tools_by_name:
                tool = tools_by_name[tool_name]
                try:
                    result = tool.invoke(tool_args)
                    print(f"[Chatbot] Tool {tool_name} result (first 200 chars): {str(result)[:200]}")
                    tool_results.append(ToolMessage(
                        content=str(result),
                        tool_call_id=tc["id"],
                    ))
                except Exception as e:
                    print(f"[Chatbot] Tool {tool_name} error: {e}")
                    tool_results.append(ToolMessage(
                        content=f"Error: {str(e)}",
                        tool_call_id=tc["id"],
                    ))
            else:
                print(f"[Chatbot] Unknown tool: {tool_name}")
                tool_results.append(ToolMessage(
                    content=f"Unknown tool: {tool_name}",
                    tool_call_id=tc["id"],
                ))
        
        # Add tool interaction to messages
        lc_messages.append(ai_msg)
        lc_messages.extend(tool_results)
        
        print(f"[Chatbot] Sending {len(lc_messages)} messages to Claude for follow-up")
        print(f"[Chatbot] Last message type: {type(lc_messages[-1]).__name__}")
        
        # Stream the final response with tool results
        async for chunk in llm.astream(lc_messages):
            if hasattr(chunk, "content") and chunk.content:
                text = extract_text(chunk.content)
                if text:
                    yield ("text", text)
