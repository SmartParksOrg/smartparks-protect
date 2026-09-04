import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { EmptyState } from "@/components/common/EmptyState";
import { Page } from "@/components/common/PageHeader";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <Page>
      <EmptyState title={t("Page not found")} description={t("The address does not exist in Smart Parks Protect.")} action={<Link className="underline" to="/projects">{t("Go to your projects")}</Link>} />
    </Page>
  );
}
