import { Link } from "react-router";

import { EmptyState } from "@/components/common/EmptyState";
import { Page } from "@/components/common/PageHeader";

export function NotFoundPage() {
  return (
    <Page>
      <EmptyState title="Page not found" description="The address does not exist in Smart Parks Protect." action={<Link className="underline" to="/projects">Go to your projects</Link>} />
    </Page>
  );
}
