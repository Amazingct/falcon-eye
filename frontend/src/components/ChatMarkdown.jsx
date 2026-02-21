import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function ChatMarkdown({ content, isUser = false }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className={`chat-markdown text-sm leading-relaxed ${isUser ? 'text-white' : 'text-gray-100'}`}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-sm font-bold mb-1.5 mt-2.5 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
        li: ({ children }) => <li className="text-sm">{children}</li>,
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer"
            className={`underline ${isUser ? 'text-blue-200 hover:text-white' : 'text-blue-400 hover:text-blue-300'}`}>
            {children}
          </a>
        ),
        code: ({ inline, className, children }) => {
          if (inline) {
            return (
              <code className={`px-1 py-0.5 rounded text-xs font-mono ${
                isUser ? 'bg-blue-500/40' : 'bg-gray-600'
              }`}>
                {children}
              </code>
            )
          }
          return (
            <pre className={`rounded-md p-3 my-2 overflow-x-auto text-xs font-mono ${
              isUser ? 'bg-blue-800/50' : 'bg-gray-900/80'
            }`}>
              <code>{children}</code>
            </pre>
          )
        },
        blockquote: ({ children }) => (
          <blockquote className={`border-l-2 pl-3 my-2 italic ${
            isUser ? 'border-blue-300/50 text-blue-100' : 'border-gray-500 text-gray-300'
          }`}>
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="text-xs border-collapse w-full">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className={`border px-2 py-1 text-left font-semibold ${
            isUser ? 'border-blue-400/30 bg-blue-700/30' : 'border-gray-600 bg-gray-700'
          }`}>{children}</th>
        ),
        td: ({ children }) => (
          <td className={`border px-2 py-1 ${
            isUser ? 'border-blue-400/30' : 'border-gray-600'
          }`}>{children}</td>
        ),
        hr: () => <hr className="my-3 border-gray-600" />,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
