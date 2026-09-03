import { Construction } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { Page, PageHeader } from "@/components/common/PageHeader";

export function ComingSoonPage({ title, phase }: { title: string; phase: number }) {
  return (
    <>
      <PageHeader title={title} />
      <Page>
        <EmptyState icon={Construction} title={`${title} arrives in phase ${phase}`} description="See PROJECT_PLAN.md for what this screen will do." />
      </Page>
    </>
  );
}
