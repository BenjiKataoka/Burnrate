import { inTauri } from "./platform.ts";

export type TrayHandlers = {
  open(): void; refresh(): void; pinned: boolean; togglePin(): void;
  atLogin: boolean; toggleLogin(): void; quit(): void;
};

export async function createTray(h: TrayHandlers): Promise<{ setTitle(title: string): Promise<void> }> {
  if (!inTauri) return { setTitle: async (title: string) => { document.title = title; } };
  const { TrayIcon } = await import("@tauri-apps/api/tray");
  const { Menu, CheckMenuItem, PredefinedMenuItem } = await import("@tauri-apps/api/menu");
  const { defaultWindowIcon } = await import("@tauri-apps/api/app");
  const pin = await CheckMenuItem.new({ id: "pin", text: "Keep widget on top", checked: h.pinned, action: h.togglePin });
  const login = await CheckMenuItem.new({ id: "login", text: "Start at login", checked: h.atLogin, action: h.toggleLogin });
  const menu = await Menu.new({
    items: [
      { id: "open", text: "Open dashboard", action: h.open },
      { id: "refresh", text: "Refresh now", action: h.refresh },
      pin,
      login,
      await PredefinedMenuItem.new({ item: "Separator" }),
      { id: "quit", text: "Quit Burnrate", action: h.quit },
    ],
  });
  const tray = await TrayIcon.new({
    id: "burnrate", icon: (await defaultWindowIcon()) ?? undefined, tooltip: "Burnrate", title: "Burnrate",
    menu, showMenuOnLeftClick: true,
  });
  return { setTitle: async (title: string) => { await tray.setTitle(title); } };
}
