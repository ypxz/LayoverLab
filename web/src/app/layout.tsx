import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: "LayoverLab — creative cheapest routes",
  description:
    "Find the absolute cheapest way between two airports: multi-day stopovers, self-transfer combos, nearby airports and ground corridors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <TooltipProvider delayDuration={200}>
          <div className="mx-auto max-w-5xl px-4 py-8">{children}</div>
        </TooltipProvider>
        <Toaster theme="dark" position="bottom-center" />
      </body>
    </html>
  );
}
