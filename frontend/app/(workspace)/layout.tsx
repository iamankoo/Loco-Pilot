import { Sidebar } from "@/components/Sidebar";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 items-start">
      <Sidebar />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
