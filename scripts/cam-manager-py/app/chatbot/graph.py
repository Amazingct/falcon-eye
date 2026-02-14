"""
LangGraph Chatbot with Claude
Streaming chat with tool support (tools added via config)
"""
import os
from typing import Annotated, TypedDict, Sequence, AsyncGenerator, Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """State for the chatbot graph"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tools: list[Any]  # Tools will be added from config


# System prompt for Falcon-Eye assistant
SYSTEM_PROMPT = """You are Falcon-Eye Assistant, an AI helper for the Falcon-Eye camera management system.

You can help users with:
- Understanding camera statuses and configurations
- Troubleshooting camera issues
- Explaining system features
- General questions about the dashboard

Be concise, helpful, and friendly. If you don't know something specific about the user's cameras, 
suggest they check the dashboard or API documentation.
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


async def stream_chat(
    messages: list[dict],
    tools: list = None,
) -> AsyncGenerator[str, None]:
    """Stream chat responses from Claude"""
    llm = get_llm(streaming=True)
    
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
    
    # Stream response
    async for chunk in llm.astream(lc_messages):
        if hasattr(chunk, "content") and chunk.content:
            yield chunk.content
