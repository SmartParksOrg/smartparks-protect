import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Dashboard, DashboardTile, Page as PageType, SavedView } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { EmptyState } from "@/components/common/EmptyState";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { AlertsTile, EntityStatusTile, EventsTile, MapTile, SavedViewTile } from "@/components/dashboards/tiles";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useAuthStore } from "@/stores/auth";

type Tile = DashboardTile;
const KINDS: Record<Tile["kind"], string> = { saved_view: "Saved view (chart)", map: "Latest positions map", alerts: "Open alerts", events: "Recent events", entity_status: "Entity status counts" };
const SIZES: Record<string, string> = { s: "col-span-12 md:col-span-4", m: "col-span-12 md:col-span-6", l: "col-span-12" };

function tileTitle(tile: Tile, views: SavedView[]): string {
  if (tile.title) return tile.title;
  if (tile.kind === "saved_view") return views.find((v) => v.id === tile.saved_view_id)?.name ?? "Saved view";
  return KINDS[tile.kind];
}

/** Project dashboards (decision D86): a shared grid of saved views and built-in tiles with a
 * size and an order. Not a Grafana clone. */
export function DashboardsPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const role = useProjectRole(projectId);
  const user = useAuthStore((s) => s.user);
  const admin = canAdmin(role) || Boolean(user?.is_superuser);
  const base = `/api/v1/projects/${projectId}/dashboards`;
  const dashboards = useQuery({ queryKey: queryKeys.dashboards(projectId), queryFn: () => api.get<PageType<Dashboard>>(base, { query: { limit: 100 } }) });
  const views = useQuery({ queryKey: queryKeys.savedViews(projectId), queryFn: () => api.get<PageType<SavedView>>(`/api/v1/projects/${projectId}/analytics/saved-views`, { query: { limit: 200 } }) });
  const selectedId = params.get("dashboard") ?? dashboards.data?.items[0]?.id ?? null;
  const current = dashboards.data?.items.find((d) => d.id === selectedId) ?? null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Tile[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const tiles: Tile[] = draft ?? ((current?.tiles ?? []) as Tile[]);
  const select = (id: string) => setParams((p) => { p.set("dashboard", id); return p; }, { replace: true });
  const create = useMutationToast({
    mutationFn: (name: string) => api.post<Dashboard>(base, { body: { name, tiles: [{ id: "map", kind: "map", size: "l" }, { id: "alerts", kind: "alerts", size: "m" }, { id: "events", kind: "events", size: "m" }] } }),
    invalidate: [queryKeys.dashboards(projectId)],
    onSuccess: (d) => { setCreating(false); setNewName(""); select(d.id); toast.success(`Dashboard ${d.name} created`); },
  });
  const save = useMutationToast({
    mutationFn: () => api.patch<Dashboard>(`${base}/${current?.id}`, { body: { tiles } }),
    invalidate: [queryKeys.dashboards(projectId)],
    success: "Dashboard saved",
    onSuccess: () => { setEditing(false); setDraft(null); },
  });
  const remove = useMutationToast({ mutationFn: () => api.delete<void>(`${base}/${current?.id}`), invalidate: [queryKeys.dashboards(projectId)], success: "Dashboard deleted", onSuccess: () => { setDeleting(false); setParams((p) => { p.delete("dashboard"); return p; }, { replace: true }); } });
  const startEdit = () => { setDraft((current?.tiles ?? []) as Tile[]); setEditing(true); };
  const move = (index: number, delta: number) => { const next = [...tiles]; const target = index + delta; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; setDraft(next); };
  const update = (index: number, patch: Partial<Tile>) => setDraft(tiles.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  const addTile = (kind: Tile["kind"], savedViewId?: string) => {
    const next = tiles.reduce((m, t) => Math.max(m, Number(t.id.split("-").pop()) || 0), 0) + 1;
    setDraft([...tiles, { id: `${kind}-${next}`, kind, size: kind === "map" ? "l" : "m", saved_view_id: savedViewId ?? null, options: {} }]);
    setAdding(false);
  };
  return (
    <>
      <PageHeader
        title="Dashboards"
        description="Saved views and live tiles on a grid, shared with the project"
        actions={<>
          {dashboards.data && dashboards.data.items.length > 0 && (
            <Select value={selectedId ?? ""} onValueChange={select}>
              <SelectTrigger className="w-56" aria-label="Dashboard"><SelectValue placeholder="Choose a dashboard" /></SelectTrigger>
              <SelectContent>{dashboards.data.items.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</SelectContent>
            </Select>
          )}
          {admin && current && !editing && <Button variant="outline" onClick={startEdit}><Pencil className="size-4" /> Edit</Button>}
          {admin && editing && <><Button variant="outline" onClick={() => setAdding(true)}><Plus className="size-4" /> Add tile</Button><Button variant="ghost" onClick={() => { setEditing(false); setDraft(null); }}>Cancel</Button><Button onClick={() => save.mutate()} disabled={save.isPending}>Save</Button></>}
          {admin && <Button onClick={() => setCreating(true)}><Plus className="size-4" /> New dashboard</Button>}
        </>}
      />
      <Page>
        {dashboards.error && <Callout kind="error">{dashboards.error.message}</Callout>}
        {dashboards.isSuccess && dashboards.data.items.length === 0 && <EmptyState title="No dashboards yet" description={admin ? "Create one: it starts with the map, open alerts and recent events, and takes saved Data Explorer views as chart tiles." : "A project admin can create dashboards."} />}
        {current && (
          <div className="grid grid-cols-12 gap-4">
            {tiles.map((tile, index) => (
              <Card key={tile.id} className={SIZES[tile.size] ?? SIZES.m}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
                  <CardTitle className="text-base">{tileTitle(tile, views.data?.items ?? [])}</CardTitle>
                  {editing && (
                    <span className="flex items-center gap-1">
                      <Select value={tile.size} onValueChange={(v) => update(index, { size: v as Tile["size"] })}>
                        <SelectTrigger className="h-7 w-24" aria-label="Tile size"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="s">small</SelectItem><SelectItem value="m">medium</SelectItem><SelectItem value="l">large</SelectItem></SelectContent>
                      </Select>
                      <Button size="icon" variant="ghost" aria-label="Move up" onClick={() => move(index, -1)}><ArrowUp className="size-4" /></Button>
                      <Button size="icon" variant="ghost" aria-label="Move down" onClick={() => move(index, 1)}><ArrowDown className="size-4" /></Button>
                      <Button size="icon" variant="ghost" aria-label="Remove tile" onClick={() => setDraft(tiles.filter((_, i) => i !== index))}><X className="size-4" /></Button>
                    </span>
                  )}
                </CardHeader>
                <CardContent className="h-72 overflow-auto">
                  {tile.kind === "saved_view" && (views.data?.items.find((v) => v.id === tile.saved_view_id) ? <SavedViewTile projectId={projectId} view={views.data.items.find((v) => v.id === tile.saved_view_id)!} /> : <p className="text-sm text-muted-foreground">The saved view no longer exists.</p>)}
                  {tile.kind === "map" && <MapTile projectId={projectId} />}
                  {tile.kind === "alerts" && <AlertsTile projectId={projectId} />}
                  {tile.kind === "events" && <EventsTile projectId={projectId} />}
                  {tile.kind === "entity_status" && <EntityStatusTile projectId={projectId} />}
                </CardContent>
              </Card>
            ))}
            {tiles.length === 0 && <div className="col-span-12 text-sm text-muted-foreground">This dashboard has no tiles yet.{admin && !editing ? " Edit it to add some." : ""}</div>}
          </div>
        )}
        {current && admin && !editing && <div className="text-right"><Button variant="ghost" size="sm" onClick={() => setDeleting(true)}><Trash2 className="size-4" /> Delete dashboard</Button></div>}
      </Page>
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>New dashboard</DialogTitle><DialogDescription>It starts with the map, open alerts and recent events; edit it afterwards.</DialogDescription></DialogHeader>
          <Field label="Name" htmlFor="dashboard-name"><Input id="dashboard-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Operations" /></Field>
          <DialogFooter><Button onClick={() => create.mutate(newName.trim())} disabled={!newName.trim() || create.isPending}>Create</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>Add a tile</DialogTitle><DialogDescription>A saved Data Explorer view, or a live tile.</DialogDescription></DialogHeader>
          <div className="space-y-2">
            {(["map", "alerts", "events", "entity_status"] as const).map((k) => <Button key={k} variant="outline" className="w-full justify-start" onClick={() => addTile(k)}>{KINDS[k]}</Button>)}
            {(views.data?.items ?? []).map((v) => <Button key={v.id} variant="outline" className="w-full justify-start" onClick={() => addTile("saved_view", v.id)}>Chart: {v.name}</Button>)}
            {views.data?.items.length === 0 && <p className="text-xs text-muted-foreground">Save a view in the Data Explorer to add charts.</p>}
          </div>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={`Delete ${current?.name}?`} description="Tiles are only layout; saved views and data stay." confirmLabel="Delete" pending={remove.isPending} onConfirm={() => remove.mutate()} />
    </>
  );
}
