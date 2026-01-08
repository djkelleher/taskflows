import { Header } from "@/components/layout";
import { ServiceTable } from "@/components/services";
import { useServices } from "@/hooks/useServices";

export function DashboardPage() {
  const { data, isLoading } = useServices();
  const services = data?.services || [];

  return (
    <>
      <Header title="Dashboard" />
      <div className="flex-1 p-6 overflow-auto">
        <ServiceTable services={services} isLoading={isLoading} />
      </div>
    </>
  );
}
