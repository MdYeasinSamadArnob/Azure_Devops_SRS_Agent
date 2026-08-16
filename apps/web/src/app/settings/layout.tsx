import { SettingsShellTemplate } from "@/components/templates/SettingsShellTemplate";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <SettingsShellTemplate>{children}</SettingsShellTemplate>;
}
