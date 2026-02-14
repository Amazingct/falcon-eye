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
) -> AsyncGenerator[str, None]:
    """Stream chat responses from Claude with tool support"""
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
    
    # First call - may return tool calls
    response = await llm.ainvoke(lc_messages)
    
    # Check for tool calls
    if hasattr(response, "tool_calls") and response.tool_calls:
        # Execute tools and get results
        tool_results = []
        tools_by_name = {t.name: t for t in tools}
        
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            
            if tool_name in tools_by_name:
                tool = tools_by_name[tool_name]
                try:
                    result = tool.invoke(tool_args)
                    tool_results.append(ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"],
                    ))
                except Exception as e:
                    tool_results.append(ToolMessage(
                        content=f"Error: {str(e)}",
                        tool_call_id=tool_call["id"],
                    ))
        
        # Add tool call and results to messages
        lc_messages.append(response)
        lc_messages.extend(tool_results)
        
        # Get final response with tool results (streaming)
        async for chunk in llm.astream(lc_messages):
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content
    else:
        # No tool calls - stream the response
        if hasattr(response, "content") and response.content:
            yield response.content
