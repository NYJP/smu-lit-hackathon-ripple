"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FilePlus2, LoaderCircle, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";

type RegulationStatus = "pending" | "processing" | "ready" | "failed";
type JobStatus = "queued" | "running" | "succeeded" | "failed";
type Regulation = { id: string; title: string; document_kind: string; status: RegulationStatus; requirement_count: number; created_at: string };
type Job = { id: string; status: JobStatus; progress: number; step: string | null; error_message: string | null };
type TrackedJob = Job & { regulationId: string };

const REGULATION_KINDS = ["primary", "amendment", "guidance", "notice", "decision", "consultation"] as const;

function label(value: string) {
  return value.replaceAll("_", " ");
}

function uploadDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

function ProgressLabel({ job }: { job: Job }) {
  return <div className="min-w-32"><div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>{job.step ?? "Processing"}</span><span>{Math.round(job.progress * 100)}%</span></div><Progress className="mt-1.5" value={job.progress * 100} />{job.error_message ? <p className="mt-1 text-xs text-destructive">{job.error_message}</p> : null}</div>;
}

export function RegulationsPageContent() {
  const { user } = useSession();
  const [items, setItems] = useState<Regulation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<(typeof REGULATION_KINDS)[number]>("primary");
  const [amends, setAmends] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [uploading, setUploading] = useState(false);
  const [jobs, setJobs] = useState<TrackedJob[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.get<{ items: Regulation[] }>("/regulations");
      setItems(result.items);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not load regulations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => {
    const activeJobs = jobs.filter((job) => job.status === "queued" || job.status === "running");
    if (activeJobs.length === 0) return;
    const poll = async () => {
      try {
        const updates = await Promise.all(activeJobs.map((job) => api.get<Job>(`/jobs/${job.id}`)));
        let hasJustFinished = false;
        setJobs((current) => current.map((job) => {
          const update = updates.find((candidate) => candidate.id === job.id);
          if (!update) return job;
          if ((job.status === "queued" || job.status === "running") && (update.status === "succeeded" || update.status === "failed")) hasJustFinished = true;
          return { ...update, regulationId: job.regulationId };
        }));
        if (hasJustFinished) void load();
      } catch {
        // A temporary polling failure should not hide the last known progress.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1200);
    return () => window.clearInterval(timer);
  }, [jobs, load]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setError("Choose a PDF to upload."); return; }
    if (kind === "amendment" && !amends) { setError("Choose the regulation this amendment updates."); return; }
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title);
      form.append("document_kind", kind);
      if (amends) form.append("amends_regulation_id", amends);
      if (effectiveDate) form.append("effective_date", effectiveDate);
      const result = await api.post<{ regulation_id: string; job_id: string }>("/regulations", undefined, { body: form });
      setJobs((current) => [{ id: result.job_id, regulationId: result.regulation_id, status: "queued", progress: 0, step: "Queued", error_message: null }, ...current]);
      setFile(null);
      setTitle("");
      setAmends("");
      setEffectiveDate("");
      setOpen(false);
      void load();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not upload the regulation.");
    } finally {
      setUploading(false);
    }
  }

  const canUpload = user?.role === "admin";
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">Uploaded sources</p><h1 className="text-2xl font-semibold tracking-tight">Regulations</h1></div>{canUpload ? <Button onClick={() => setOpen(true)}><FilePlus2 />Upload regulation</Button> : null}</div>
    {error ? <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p> : null}
    {!canUpload ? <p className="mt-5 rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">Only an admin can upload regulations.</p> : null}
    <div className="mt-5 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Title</TableHead><TableHead>Kind</TableHead><TableHead>Status</TableHead><TableHead>Requirements</TableHead><TableHead>Uploaded</TableHead></TableRow></TableHeader><TableBody>
      {loading ? <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground"><LoaderCircle className="mx-auto mb-2 animate-spin" />Loading regulations</TableCell></TableRow> : null}
      {!loading && items.length === 0 ? <TableRow><TableCell colSpan={5} className="py-12 text-center text-muted-foreground">No regulations uploaded yet.</TableCell></TableRow> : null}
      {!loading ? items.map((item) => { const job = jobs.find((candidate) => candidate.regulationId === item.id); return <TableRow key={item.id}><TableCell className="font-medium"><Link className="hover:underline" href={`/regulations/${item.id}`}>{item.title}</Link></TableCell><TableCell className="capitalize">{label(item.document_kind)}</TableCell><TableCell>{job && (job.status === "queued" || job.status === "running") ? <ProgressLabel job={job} /> : <Badge variant={item.status === "failed" ? "destructive" : item.status === "ready" ? "default" : "outline"}>{item.status}</Badge>}</TableCell><TableCell>{item.requirement_count}</TableCell><TableCell className="whitespace-nowrap text-muted-foreground">{uploadDate(item.created_at)}</TableCell></TableRow>; }) : null}
    </TableBody></Table></div>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-md"><DialogHeader><DialogTitle>Upload regulation</DialogTitle><DialogDescription>Add a PDF source and, where needed, relate it to the regulation it updates.</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-5"><div className="space-y-2"><Label htmlFor="regulation-file">PDF file</Label><Input id="regulation-file" type="file" accept=".pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></div><div className="space-y-2"><Label htmlFor="regulation-title">Title</Label><Input id="regulation-title" required value={title} onChange={(event) => setTitle(event.target.value)} /></div><div className="space-y-2"><Label>Kind</Label><Select value={kind} onValueChange={(value) => setKind(value as typeof kind)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{REGULATION_KINDS.map((value) => <SelectItem key={value} value={value} className="capitalize">{label(value)}</SelectItem>)}</SelectContent></Select></div>{kind === "amendment" ? <div className="space-y-2"><Label>This amends</Label><Select value={amends} onValueChange={setAmends}><SelectTrigger className="w-full"><SelectValue placeholder="Select a regulation" /></SelectTrigger><SelectContent>{items.map((item) => <SelectItem key={item.id} value={item.id}>{item.title}</SelectItem>)}</SelectContent></Select></div> : null}<div className="space-y-2"><Label htmlFor="effective-date">Effective date</Label><Input id="effective-date" type="date" value={effectiveDate} onChange={(event) => setEffectiveDate(event.target.value)} /></div><DialogFooter><Button type="submit" disabled={uploading}>{uploading ? <LoaderCircle className="animate-spin" /> : <Upload />}Upload regulation</Button></DialogFooter></form></DialogContent></Dialog>
  </div>;
}
