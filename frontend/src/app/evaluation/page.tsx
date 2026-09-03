import { EvaluationView } from "@/components/evaluation/EvaluationView";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function EvaluationPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Link
          href="/"
          className="text-xs font-mono text-slate-400 hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Volver al inicio
        </Link>
      </div>

      <EvaluationView />
    </div>
  );
}
