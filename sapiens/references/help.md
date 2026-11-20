# sapiens: how to use it

A way of writing answers that is **concise and complete** at the same time.

- It keeps full sentences, the *why*, caveats and useful findings.
- It cuts preamble, restating your question, piles of "maybe", and summaries
  that repeat what was just said.
- It uses tables, lists, diagrams and code whenever they get the point across
  faster.

It sits between Claude's default style, which can run long, and "caveman",
which is so terse it loses the reasoning.

## Turning it on and off

| You say | What happens |
|---|---|
| `/sapiens` | On. It stays on for every later answer in the chat. |
| "sapiens mode", "be concise but thorough", "to the point but complete", "meno prolisso" | On, the same way. |
| "stop sapiens", "normal mode" | Off: back to the default style. |
| `/sapiens help` | This page. |

It works in any language.

## An example

**Question:** "why is my React component re-rendering?"

**Default** (it answers, but pads it out):
> Great question! Re-renders in React can happen for many reasons. Let me walk
> you through it… *(three paragraphs, then a summary that repeats the fix)*

**Caveman** (right, but with no *why*):
> `Inline obj prop -> new ref -> re-render. useMemo.`

**Sapiens:**
> An inline object/array/function prop creates a new reference every render, so
> the child's prop-equality check always fails and it re-renders. Wrap the value
> in `useMemo` (or the callback in `useCallback`).
>
> Caveat: only worth it if the child is memoized (`React.memo`) or the value
> feeds a dependency array, otherwise memoization costs more than it saves.

## When it gets longer on purpose

- security warnings;
- confirming destructive actions;
- step-by-step procedures where the order matters.

In those cases being clear matters more than being short.
