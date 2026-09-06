/**
 * Word-level redline, for showing what a proposed edit actually changes.
 *
 * A reviewer approving wording needs to see the *difference*, not two
 * paragraphs to read twice — the whole point of the "minimal edit" prompt in
 * api/services/recommendations.py is that the change should be small, and a
 * side-by-side of two near-identical texts hides exactly that.
 *
 * Standard LCS over whitespace-delimited tokens. The texts here are single
 * clauses (tens of words), so the O(n·m) table is the right trade for exact
 * output; guard rails below fall back to a whole-block replace if a caller
 * ever hands this something document-sized.
 */

export type DiffOp = "equal" | "insert" | "delete";

export interface DiffToken {
  op: DiffOp;
  /** Includes the trailing whitespace, so joining segments restores the text. */
  text: string;
}

/** Beyond this the table is not worth building; render a block replace instead. */
const MAX_TOKENS = 600;

/** Split into words, keeping each token's trailing whitespace attached. */
function tokenize(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

export function diffWords(before: string, after: string): DiffToken[] {
  const a = tokenize(before);
  const b = tokenize(after);

  if (a.length === 0 && b.length === 0) return [];
  if (a.length > MAX_TOKENS || b.length > MAX_TOKENS) {
    return [
      { op: "delete", text: before },
      { op: "insert", text: after },
    ];
  }

  // table[i][j] = length of the LCS of a[i..] and b[j..].
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        a[i].trim() === b[j].trim()
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const out: DiffToken[] = [];
  const push = (op: DiffOp, text: string) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };

  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i].trim() === b[j].trim()) {
      push("equal", a[i]);
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      push("delete", a[i]);
      i += 1;
    } else {
      push("insert", b[j]);
      j += 1;
    }
  }
  while (i < a.length) push("delete", a[(i += 1) - 1]);
  while (j < b.length) push("insert", b[(j += 1) - 1]);

  return out;
}

/** True when the edit is nothing but whitespace — worth saying so outright. */
export function isUnchanged(before: string, after: string): boolean {
  return before.trim() === after.trim();
}

/**
 * Split `text` into the part before a span, the span, and the part after.
 * Returns a single "before" segment when the offsets are missing or absurd,
 * so a bad span degrades to plain text rather than to a scrambled clause.
 */
export function splitSpan(
  text: string,
  start: number | null | undefined,
  end: number | null | undefined,
): { before: string; span: string; after: string } {
  if (
    start === null || start === undefined ||
    end === null || end === undefined ||
    start < 0 || end > text.length || start >= end
  ) {
    return { before: text, span: "", after: "" };
  }
  return { before: text.slice(0, start), span: text.slice(start, end), after: text.slice(end) };
}
