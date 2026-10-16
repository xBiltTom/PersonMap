import { InvestigationForm } from "@/components/investigation/InvestigationForm";

export default function NewAuditPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-4 border-b border-[#162234] pb-3">
        <p className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-sky-300">Auditorías</p>
        <h1 className="mt-1 text-2xl font-extrabold leading-tight tracking-[-0.045em] text-slate-50">
          Nueva auditoría
        </h1>
      </header>
      <InvestigationForm />
    </div>
  );
}
