import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device, DeviceType, Page as PageType } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Icon } from "@/components/icons/Icon";
import { formatAgo } from "@/lib/format";

export function DevicesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const devices = useQuery({ queryKey: queryKeys.devices({ projectId }), queryFn: () => api.get<PageType<Device>>("/api/v1/devices", { query: { project_id: projectId, limit: 500 } }) });
  const types = useQuery({ queryKey: queryKeys.deviceTypes, queryFn: () => api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }) });
  const typeById = new Map(types.data?.items.map((t) => [t.id, t]));
  const columns: ColumnDef<Device, unknown>[] = [
    { header: t("Name"), accessorKey: "name", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={typeById.get(row.original.device_type_id)?.icon_key} />{row.original.name}</span> },
    { header: t("Type"), accessorFn: (d) => typeById.get(d.device_type_id)?.label ?? "" },
    { header: t("Driver"), accessorFn: (d) => typeById.get(d.device_type_id)?.driver_key ?? "" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Serial"), accessorKey: "serial_number" },
    { header: t("Updated"), accessorKey: "updated_at", cell: ({ getValue }) => formatAgo(getValue<string>()) },
  ];
  return (
    <>
      <PageHeader title={t("Devices")} description={t("Hardware currently assigned to this project")} />
      <Page>
        <DataTable columns={columns} data={devices.data?.items} isLoading={devices.isPending} emptyMessage={t("No devices are assigned to this project.")} onRowClick={(d) => navigate(`/projects/${projectId}/devices/${d.id}`)} />
      </Page>
    </>
  );
}
