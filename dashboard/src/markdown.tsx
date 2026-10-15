import { isValidElement, type ComponentProps, type ElementType, type ReactNode } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CopyButton } from "./copy-button";

/** An element in the dashboard's look (react-markdown's `node` prop stays off the DOM). */
function styled<T extends ElementType>(Tag: T, className: string, extra?: ComponentProps<T>) {
  return function Styled({ node, ...props }: ComponentProps<T> & ExtraProps) {
    void node;
    const Element = Tag as ElementType;
    return <Element className={className} {...extra} {...props} />;
  };
}

const FIRST_LAST = "first:mt-0 last:mb-0";

/** Blocks of words to paste somewhere (```text, ```email...): shown in the normal font, not as code. */
const PASTE = new Set(["text", "txt", "plain", "copy", "email", "message", "post", "reply", "draft", "note"]);

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

/**
 * A fenced block: code with its language and a Copy button, or, for ```text and the like, words to
 * paste (an email, a post) in the normal font with a Copy button of its own.
 */
function Snippet({ node, children }: ComponentProps<"pre"> & ExtraProps) {
  void node;
  const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children : null;
  const lang = (code?.props.className ?? "").match(/language-([\w+#-]+)/)?.[1]?.toLowerCase() ?? "";
  const text = textOf(code ? code.props.children : children).replace(/\n$/, "");
  if (PASTE.has(lang)) {
    return (
      <div className={`my-2 rounded-xl border border-line bg-bg ${FIRST_LAST}`}>
        <div className="flex items-center justify-between border-b border-line py-1 pr-1.5 pl-3">
          <span className="text-xs text-ink-3">{lang === "text" || lang === "txt" || lang === "plain" || lang === "copy" ? "Text to copy" : lang[0].toUpperCase() + lang.slice(1)}</span>
          <CopyButton text={text} label="Copy the text" showLabel />
        </div>
        <p className="px-3 py-2.5 leading-relaxed whitespace-pre-wrap" dir="auto">
          {text}
        </p>
      </div>
    );
  }
  return (
    <div className={`my-2 overflow-hidden rounded-xl bg-surface-2 ${FIRST_LAST}`}>
      <div className="flex items-center justify-between py-1 pr-1.5 pl-3">
        <span className="font-mono text-xs text-ink-3">{lang || "code"}</span>
        <CopyButton text={text} label="Copy the code" showLabel />
      </div>
      <pre className="overflow-x-auto px-3 pb-3 font-mono text-sm leading-snug" dir="ltr">
        <code>{text}</code>
      </pre>
    </div>
  );
}

/** Raw HTML in the text is shown as text, never run. Images show their description only. */
const COMPONENTS: Components = {
  p: styled("p", `my-2 ${FIRST_LAST}`),
  h1: styled("h3", `mt-4 mb-2 font-display text-lg ${FIRST_LAST}`),
  h2: styled("h3", `mt-4 mb-2 font-display text-lg ${FIRST_LAST}`),
  h3: styled("h4", `mt-3 mb-1.5 font-semibold ${FIRST_LAST}`),
  h4: styled("h4", `mt-3 mb-1.5 font-semibold ${FIRST_LAST}`),
  ul: styled("ul", `my-2 list-disc space-y-1 pl-5 marker:text-ink-3 ${FIRST_LAST}`),
  ol: styled("ol", `my-2 list-decimal space-y-1 pl-5 marker:text-ink-3 ${FIRST_LAST}`),
  li: styled("li", "pl-0.5 [&>ol]:my-1 [&>ul]:my-1 [&>p]:my-1"),
  strong: styled("strong", "font-semibold"),
  a: styled("a", "text-accent underline underline-offset-2 hover:text-accent-hover", { target: "_blank", rel: "noopener noreferrer" }),
  blockquote: styled("blockquote", `my-2 border-l-2 border-line pl-3 text-ink-2 ${FIRST_LAST}`),
  hr: styled("hr", "my-3 border-line"),
  code: styled("code", "rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.9em]"),
  pre: Snippet,
  table: ({ node, ...props }) => {
    void node;
    return (
      <div className={`my-2 overflow-x-auto rounded-xl border border-line ${FIRST_LAST}`}>
        <table className="w-full border-collapse text-sm" {...props} />
      </div>
    );
  },
  th: styled("th", "border-b border-line bg-surface-2 px-3 py-1.5 text-left font-semibold"),
  td: styled("td", "border-b border-line px-3 py-1.5 align-top [tr:last-child>&]:border-b-0"),
  img: ({ alt }) => <span>{alt}</span>,
};

/** The COO's words, which may use Markdown: bold, lists, links, tables, code and text to copy. */
export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
}
