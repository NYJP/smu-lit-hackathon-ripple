"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, LoaderCircle, Search } from "lucide-react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import type { TextItem, TextMarkedContent } from "pdfjs-dist/types/src/display/api";

import { Button } from "@/components/ui/button";

type Match = { page: number; itemIndexes: number[] };
type Highlight = { left: number; top: number; width: number; height: number };

function words(value: string) {
  return (value.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).map((word) => {
    if (word.length > 5 && word.endsWith("ing")) return word.slice(0, -3);
    if (word.length > 4 && word.endsWith("ed")) return word.slice(0, -2);
    if (word.length > 3 && word.endsWith("s")) return word.slice(0, -1);
    return word;
  });
}

function textItems(items: Array<TextItem | TextMarkedContent>) {
  return items.filter((item): item is TextItem => "str" in item);
}

async function findQuotation(pdf: PDFDocumentProxy, quotation: string, preferredPage?: number | null): Promise<Match | null> {
  const target = words(quotation);
  if (!target.length) return null;
  const targetSet = new Set(target);
  const pages = Array.from({ length: pdf.numPages }, (_, index) => index + 1);
  if (preferredPage && preferredPage >= 1 && preferredPage <= pdf.numPages) {
    pages.splice(pages.indexOf(preferredPage), 1);
    pages.unshift(preferredPage);
  }
  let best: { match: Match; score: number } | null = null;
  for (const pageNumber of pages) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const flattened = textItems(content.items).flatMap((item, itemIndex) => words(item.str).map((word) => ({ word, itemIndex })));
    for (let start = 0; start <= flattened.length - target.length; start += 1) {
      if (target.every((word, offset) => flattened[start + offset].word === word)) {
        return { page: pageNumber, itemIndexes: [...new Set(flattened.slice(start, start + target.length).map((entry) => entry.itemIndex))] };
      }
    }
    const lengths = [...new Set([target.length, Math.round(target.length * 1.5), target.length * 2])];
    for (const length of lengths) {
      for (let start = 0; start <= flattened.length - length; start += 1) {
        const window = flattened.slice(start, start + length);
        const candidateSet = new Set(window.map((entry) => entry.word));
        const shared = [...targetSet].filter((word) => candidateSet.has(word)).length;
        const coverage = shared / targetSet.size;
        const density = shared / candidateSet.size;
        const score = coverage * 0.8 + density * 0.2;
        if (score > (best?.score ?? 0)) {
          best = { score, match: { page: pageNumber, itemIndexes: [...new Set(window.map((entry) => entry.itemIndex))] } };
        }
      }
    }
  }
  return best && best.score >= 0.58 ? best.match : null;
}

function multiply(left: number[], right: number[]) {
  return [
    left[0] * right[0] + left[2] * right[1],
    left[1] * right[0] + left[3] * right[1],
    left[0] * right[2] + left[2] * right[3],
    left[1] * right[2] + left[3] * right[3],
    left[0] * right[4] + left[2] * right[5] + left[4],
    left[1] * right[4] + left[3] * right[5] + left[5],
  ];
}

export function RegulationPdfViewer({ src, title, quotation, preferredPage }: { src: string; title: string; quotation: string | null; preferredPage?: number | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(preferredPage ?? 1);
  const [pageCount, setPageCount] = useState(0);
  const [match, setMatch] = useState<Match | null>(null);
  const [matchState, setMatchState] = useState<"searching" | "matched" | "unmatched">("searching");
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: ReturnType<(typeof import("pdfjs-dist"))["getDocument"]> | null = null;
    void import("pdfjs-dist").then(async (pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
      loadingTask = pdfjs.getDocument({ url: src, withCredentials: true });
      const pdf = await loadingTask.promise;
      if (cancelled) return;
      pdfRef.current = pdf;
      setPageCount(pdf.numPages);
      const result = quotation ? await findQuotation(pdf, quotation, preferredPage) : null;
      if (cancelled) return;
      setMatch(result);
      setMatchState(result ? "matched" : "unmatched");
      setPageNumber(result?.page ?? (preferredPage && preferredPage <= pdf.numPages ? preferredPage : 1));
    }).catch(() => {
      if (!cancelled) setError("The source PDF could not be rendered.");
    });
    return () => {
      cancelled = true;
      void loadingTask?.destroy();
      pdfRef.current = null;
    };
  }, [preferredPage, quotation, src]);

  useEffect(() => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    if (!pdf || !canvas || !pageCount) return;
    let cancelled = false;
    let renderTask: ReturnType<PDFPageProxy["render"]> | undefined;
    void pdf.getPage(pageNumber).then(async (page) => {
      const viewport = page.getViewport({ scale: 1.4 });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      renderTask = page.render({ canvas, viewport });
      await renderTask.promise;
      if (cancelled) return;
      if (match?.page !== pageNumber) {
        setHighlights([]);
        return;
      }
      const content = await page.getTextContent();
      const items = textItems(content.items);
      setHighlights(match.itemIndexes.flatMap((index) => {
        const item = items[index];
        if (!item) return [];
        const transform = multiply(viewport.transform, item.transform as number[]);
        const height = Math.max(Math.hypot(transform[2], transform[3]), 8);
        return [{ left: transform[4], top: transform[5] - height, width: Math.max(item.width * viewport.scale, 4), height }];
      }));
    }).catch(() => {
      if (!cancelled) setError("This PDF page could not be rendered.");
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [match, pageCount, pageNumber]);

  if (error) return <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>;

  return <div className="overflow-hidden rounded-lg border bg-muted/20">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-3">
      <div className="flex items-center gap-2 text-sm"><Search className="size-4" />{matchState === "searching" ? "Locating cited clause…" : matchState === "matched" ? `Referenced clause highlighted on page ${match?.page}` : "Referenced clause could not be located in the PDF text"}</div>
      <div className="flex items-center gap-2"><Button type="button" size="icon-sm" variant="outline" aria-label="Previous PDF page" disabled={pageNumber <= 1} onClick={() => setPageNumber((page) => page - 1)}><ChevronLeft /></Button><span className="min-w-20 text-center text-xs text-muted-foreground">Page {pageNumber}{pageCount ? ` of ${pageCount}` : ""}</span><Button type="button" size="icon-sm" variant="outline" aria-label="Next PDF page" disabled={!pageCount || pageNumber >= pageCount} onClick={() => setPageNumber((page) => page + 1)}><ChevronRight /></Button></div>
    </div>
    {matchState === "unmatched" && quotation ? <div className="border-b border-yellow-300 bg-yellow-50 p-4 text-sm dark:border-yellow-700 dark:bg-yellow-950/30"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Cited regulation text</p><mark className="mt-2 block bg-yellow-200/80 text-foreground dark:bg-yellow-500/40">{quotation}</mark></div> : null}
    <div className="max-h-[70vh] overflow-auto p-4">
      <div className="relative mx-auto w-fit bg-white shadow-sm" aria-label={`${title}, page ${pageNumber}`}>
        {!pageCount ? <div className="flex h-96 w-72 items-center justify-center"><LoaderCircle className="animate-spin text-muted-foreground" /></div> : null}
        <canvas ref={canvasRef} className={pageCount ? "block" : "hidden"} />
        {highlights.map((highlight, index) => <span key={`${highlight.left}-${highlight.top}-${index}`} className="pointer-events-none absolute rounded-sm bg-yellow-300/60 ring-2 ring-yellow-500/80 mix-blend-multiply" style={{ left: highlight.left, top: highlight.top, width: highlight.width, height: highlight.height }} />)}
      </div>
    </div>
  </div>;
}
