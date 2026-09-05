"use client";

import { useCallback, useEffect, useState } from "react";
import { FilePlus2, LoaderCircle, Upload } from "lucide-react";
import Link from "next/link";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Scope = "all" | "mine" | "shared_with_me";
type DocumentItem = {
  id: string;
  name: string;
  doc_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  page_count: number | null;
  chunk_count: number;
  open_impact_count: number;
  owner: { id: string; display_name: string };
  collaborators: Array<{ id: string; display_name: string }>;
  contributors: Array<{ id: string; display_name: string }>;
};
type Job = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  step: string | null;
  error_message: string | null;
};
const types = [
  "policy",
  "playbook",
  "sop",
  "template",
  "clause_library",
  "checklist",
  "opinion",
  "advisory",
  "training",
  "other",
];

export function DocumentsPageContent() {
  const { user, roster } = useSession();
  const [scope, setScope] = useState<Scope>("all");
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [docType, setDocType] = useState("policy");
  const [tagged, setTagged] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(
        (await api.get<{ items: DocumentItem[] }>(`/documents?scope=${scope}`))
          .items,
      );
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not load documents.",
      );
    } finally {
      setLoading(false);
    }
  }, [scope]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  useEffect(() => {
    if (
      !jobs.some((job) => job.status === "queued" || job.status === "running")
    )
      return;
    const timer = window.setInterval(
      () =>
        void Promise.all(jobs.map((job) => api.get<Job>(`/jobs/${job.id}`)))
          .then((updated) => {
            setJobs(updated);
            if (
              updated.every(
                (job) => job.status === "succeeded" || job.status === "failed",
              )
            )
              void load();
          })
          .catch(() => undefined),
      1200,
    );
    return () => window.clearInterval(timer);
  }, [jobs, load]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length)
      return setError("Choose at least one document to upload.");
    setUploading(true);
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files[]", file));
      form.append("doc_type", docType);
      form.append("collaborator_access", "reviewer");
      tagged.forEach((id) => form.append("collaborator_ids[]", id));
      const result = await api.post<{ documents: Array<{ job_id: string }> }>(
        "/documents",
        undefined,
        { body: form },
      );
      setJobs(
        result.documents.map(({ job_id }) => ({
          id: job_id,
          status: "queued",
          progress: 0,
          step: "Queued",
          error_message: null,
        })),
      );
      setOpen(false);
      setFiles([]);
      setTagged([]);
      void load();
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not upload documents.",
      );
    } finally {
      setUploading(false);
    }
  }
  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">Internal corpus</p>
          <h1 className="text-2xl font-semibold">Documents</h1>
        </div>
        <Button onClick={() => setOpen(true)}>
          <FilePlus2 />
          Add documents
        </Button>
      </div>
      <Tabs
        value={scope}
        onValueChange={(value) => setScope(value as Scope)}
        className="mt-7"
      >
        <TabsList variant="line">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="mine">Mine</TabsTrigger>
          <TabsTrigger value="shared_with_me">Shared with me</TabsTrigger>
        </TabsList>
      </Tabs>
      {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
      {jobs.length > 0 && (
        <div className="mt-5 space-y-3 rounded-lg border p-4">
          {jobs.map((job) => (
            <div key={job.id}>
              <div className="flex justify-between text-sm">
                <span>{job.step ?? "Processing"}</span>
                <span>{Math.round(job.progress * 100)}%</span>
              </div>
              <Progress className="mt-2" value={job.progress * 100} />
            </div>
          ))}
        </div>
      )}
      <div className="mt-5 rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Contributors</TableHead>
              <TableHead>Issues</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-muted-foreground"
                >
                  <LoaderCircle className="mx-auto animate-spin" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-muted-foreground"
                >
                  No documents in this view yet.
                </TableCell>
              </TableRow>
            ) : (
              items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">
                    <Link className="hover:underline" href={`/documents/${item.id}`}>
                      {item.name}
                    </Link>
                  </TableCell>
                  <TableCell className="capitalize">
                    {item.doc_type.replace("_", " ")}
                  </TableCell>
                  <TableCell>{item.owner.display_name}</TableCell>
                  <TableCell>
                    {item.contributors.length
                      ? item.contributors
                          .map((person) => person.display_name)
                          .join(", ")
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.open_impact_count > 0 ? "destructive" : "outline"}>
                      {item.open_impact_count} {item.open_impact_count === 1 ? "issue" : "issues"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        item.status === "failed"
                          ? "destructive"
                          : item.status === "ready"
                            ? "default"
                            : "outline"
                      }
                    >
                      {item.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Add documents</SheetTitle>
            <SheetDescription>
              Upload PDF, DOCX, or TXT files and tag colleagues who should be
              able to review them.
            </SheetDescription>
          </SheetHeader>
          <form onSubmit={submit} className="space-y-5 p-4">
            <div>
              <Label htmlFor="files">Files</Label>
              <Input
                id="files"
                type="file"
                accept=".pdf,.docx,.txt"
                multiple
                onChange={(event) =>
                  setFiles(Array.from(event.target.files ?? []))
                }
              />
            </div>
            <div>
              <Label>Document type</Label>
              <Select value={docType} onValueChange={setDocType}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {types.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type.replace("_", " ")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Tag colleagues</Label>
              {roster
                .filter((person) => person.id !== user?.id)
                .map((person) => (
                  <label
                    key={person.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <Checkbox
                      checked={tagged.includes(person.id)}
                      onCheckedChange={() =>
                        setTagged((current) =>
                          current.includes(person.id)
                            ? current.filter((id) => id !== person.id)
                            : [...current, person.id],
                        )
                      }
                    />
                    {person.display_name}
                  </label>
                ))}
            </div>
            <Button type="submit" disabled={uploading} className="w-full">
              {uploading ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Upload />
              )}
              Upload documents
            </Button>
          </form>
        </SheetContent>
      </Sheet>
    </div>
  );
}
