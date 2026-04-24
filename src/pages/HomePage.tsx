import { Bot } from "lucide-react";
import { Link } from "react-router-dom";
import { DashboardLayout } from "@/components/dashboard/DashboardLayout";
import { cn } from "@/lib/utils";

const HomePage = () => {
  return (
    <DashboardLayout title="Home">
      <div
        className={cn(
          "flex min-h-0 flex-col items-center justify-center",
          "py-8 md:py-12",
        )}
      >
        <div
          className={cn(
            "flex max-w-md flex-col items-center text-center",
            "rounded-lg bg-[#1a1a1a] px-8 py-10 ring-1 ring-inset ring-white/[0.06]",
          )}
        >
          <div
            className={cn(
              "mb-4 flex h-16 w-16 items-center justify-center rounded-2xl",
              "bg-white/[0.06] text-[#ededed]",
            )}
            aria-hidden
          >
            <Bot className="h-8 w-8" strokeWidth={1.75} />
          </div>
          <h1 className="text-[16px] font-semibold text-[#ededed]">No bots yet</h1>
          <p className="mt-2 text-[13px] leading-snug text-[#919191]">
            This space is empty. Add automations from{" "}
            <Link to="/strategies" className="text-[#0070f3] hover:underline">
              Strategies
            </Link>{" "}
            when you are ready.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
};

export default HomePage;
