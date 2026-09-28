import { inTauri } from "./platform.ts";

export type TrayHandlers = {
  open(): void; refresh(): void; pinned: boolean; togglePin(): boolean;
  atLogin: boolean; toggleLogin(): Promise<boolean>; quit(): void;
};

export async function createTray(h: TrayHandlers): Promise<{ setTitle(title: string): Promise<void> }> {
  if (!inTauri) return { setTitle: async (title: string) => { document.title = title; } };
  const { TrayIcon } = await import("@tauri-apps/api/tray");
  const { Menu, MenuItem, CheckMenuItem, PredefinedMenuItem } = await import("@tauri-apps/api/menu");
  const { defaultWindowIcon } = await import("@tauri-apps/api/app");
  // The item's own checked state can drift from the real one (a click already flips it
  // visually), so every toggle re-asserts the true value with setChecked.
  let pin: Awaited<ReturnType<typeof CheckMenuItem.new>>;
  pin = await CheckMenuItem.new({
    id: "pin", text: "Keep widget on top", checked: h.pinned,
    action: () => { void pin.setChecked(h.togglePin()); },
  });
  let login: Awaited<ReturnType<typeof CheckMenuItem.new>>;
  login = await CheckMenuItem.new({
    id: "login", text: "Start at login", checked: h.atLogin,
    action: () => { void h.toggleLogin().then((value) => login.setChecked(value)); },
  });
  // Items must be created with .new(): object literals inside Menu.new are dropped once the
  // menu is built, and Tauri drops their click handlers with them (tauri 2.12 menu/plugin.rs).
  const menu = await Menu.new({
    items: [
      await MenuItem.new({ id: "open", text: "Open dashboard", action: h.open }),
      await MenuItem.new({ id: "refresh", text: "Refresh now", action: h.refresh }),
      pin,
      login,
      await PredefinedMenuItem.new({ item: "Separator" }),
      await MenuItem.new({ id: "quit", text: "Quit Burnrate", action: h.quit }),
    ],
  });
  const tray = await TrayIcon.new({
    id: "burnrate", icon: (await defaultWindowIcon()) ?? undefined, tooltip: "Burnrate", title: "Burnrate",
    menu, showMenuOnLeftClick: true,
  });
  return { setTitle: async (title: string) => { await tray.setTitle(title); } };
}
