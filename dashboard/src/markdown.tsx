import type { ComponentProps, ElementType } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";

/** An element in the dashboard's look (react-markdown's `node` prop stays off the DOM). */
function styled<T extends ElementType>(Tag: T, className: string, extra?: ComponentProps<T>) {
  return function Styled({ node, ...props }: ComponentProps<T> & ExtraProps) {
    void node;
    const Element = Tag as ElementType;
    return <Element className={className} {...extra} {...props} />;
  };
}

const FIRST_LAST = "first:mt-0 last:mb-0";

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
  pre: styled("pre", `my-2 overflow-x-auto rounded-xl bg-surface-2 p-3 font-mono text-sm leading-snug [&_code]:bg-transparent [&_code]:p-0 ${FIRST_LAST}`),
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

/** The COO's words, which may use Markdown: bold, lists, links, tables, code. */
export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
}
