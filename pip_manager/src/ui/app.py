import threading
import webbrowser

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src.core import pip_wrapper, pypi

CHECKED = "☑"
UNCHECKED = "☐"


class PipManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Менеджер pip-пакетов")
        self.root.geometry("780x560")

        self.descriptions = pypi.DescriptionService()
        self.packages = []
        self.row_packages = {}
        self.name_to_iid = {}
        self.checked = set()
        self._click_timer = None

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        env = pip_wrapper.get_environment_info()
        env_text = (
            f"Python {env['version']}  |  "
            f"{'venv' if env['is_venv'] else 'системный'}  |  {env['executable']}"
        )
        env_frame = ttk.Frame(self.root)
        env_frame.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(env_frame, text=env_text, foreground="#555").pack(side=tk.LEFT)

        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=8, pady=8)

        ttk.Button(toolbar, text="Обновить", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Удалить выбранные", command=self.uninstall_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Удалить все", command=self.uninstall_all).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Выбрать всё", command=self._select_all_visible).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(toolbar, text="Снять выбор", command=self._clear_selection).pack(side=tk.LEFT, padx=6)

        self.status = tk.StringVar(value="Готово")
        ttk.Label(toolbar, textvariable=self.status).pack(side=tk.RIGHT)

        options = ttk.Frame(self.root)
        options.pack(fill=tk.X, padx=8)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Label(options, text="Поиск:").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.filter_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        self.only_groups_var = tk.BooleanVar(value=False)
        self.only_groups_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Checkbutton(options, text="Только группы (>1 пакета)", variable=self.only_groups_var).pack(side=tk.LEFT)

        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.tree = ttk.Treeview(
            body, columns=("sel", "name", "version", "desc"),
            show="headings", selectmode="extended",
        )
        self.tree.heading("sel", text="✓")
        self.tree.heading("name", text="Пакет")
        self.tree.heading("version", text="Версия")
        self.tree.heading("desc", text="Описание")
        self.tree.column("sel", width=30, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=200, stretch=False)
        self.tree.column("version", width=90, stretch=False)
        self.tree.column("desc", stretch=True)

        tree_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(body, width=210)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        ttk.Label(right, text="Группы (>1 пакета)").pack(anchor=tk.W)
        self.group_list = tk.Listbox(right)
        group_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.group_list.yview)
        self.group_list.configure(yscrollcommand=group_scroll.set)
        self.group_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        group_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.group_list.bind("<<ListboxSelect>>", self._on_group_select)

        self.family_iids = {}

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Delete>", lambda _: self.uninstall_selected())
        self.tree.bind("<Control-a>", lambda _: self._select_all_visible())

    def refresh(self):
        self.status.set("Загрузка списка...")
        self.root.update_idletasks()

        def work():
            try:
                self.packages = pip_wrapper.get_installed_packages()
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
                self.root.after(0, lambda: self.status.set("Ошибка"))
                return
            self.root.after(0, self._apply_filter)
            self.root.after(0, lambda: threading.Thread(
                target=self.fetch_descriptions, args=([p["name"] for p in self.packages],), daemon=True
            ).start())

        threading.Thread(target=work, daemon=True).start()

    def _apply_filter(self, *_):
        pattern = self.filter_var.get().strip().lower()
        only_groups = self.only_groups_var.get()

        families = {}
        for pkg in self.packages:
            if pattern and pattern not in pkg["name"].lower():
                continue
            fam = pip_wrapper.family_of(pkg["name"])
            families.setdefault(fam, []).append(pkg)

        multi_families = {f: ps for f, ps in families.items() if len(ps) > 1}
        tree_families = multi_families if only_groups else families

        self.group_list.delete(0, tk.END)
        self.family_iids = {}
        for fam in sorted(multi_families):
            self.group_list.insert(tk.END, f"{fam} ({len(multi_families[fam])})")

        self.tree.delete(*self.tree.get_children())
        self.row_packages = {}
        self.name_to_iid = {}

        for fam in sorted(tree_families):
            iids = []
            for pkg in tree_families[fam]:
                name = pkg["name"]
                mark = CHECKED if name in self.checked else UNCHECKED
                iid = self.tree.insert("", tk.END, values=(
                    mark, name, pkg["version"], self.descriptions.get(name),
                ))
                self.row_packages[iid] = [name]
                self.name_to_iid[name] = iid
                iids.append(iid)
            self.family_iids[fam] = iids

        self.status.set(f"Пакетов: {len(self.packages)}  |  групп >1: {len(multi_families)}  |  показано: {len(self.tree.get_children())}")

    def _on_group_select(self, *_):
        sel = self.group_list.curselection()
        if not sel:
            return
        label = self.group_list.get(sel[0])
        fam = label.rsplit(" (", 1)[0]
        names = [self.tree.item(iid, "values")[1] for iid in self.family_iids.get(fam, [])]
        self.checked.update(names)
        self._render_checks()
        if names:
            self.tree.see(self.name_to_iid[names[0]])

    def _render_checks(self):
        for iid in self.tree.get_children():
            name = self.tree.item(iid, "values")[1]
            self.tree.set(iid, "sel", CHECKED if name in self.checked else UNCHECKED)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        name = self.tree.item(iid, "values")[1]
        self._click_timer = self.root.after(250, lambda: self._toggle(name))

    def _on_double(self, event):
        if self._click_timer:
            self.root.after_cancel(self._click_timer)
            self._click_timer = None
        iid = self.tree.identify_row(event.y)
        if iid:
            self._open_pypi(self.tree.item(iid, "values")[1])

    def _toggle(self, name):
        self._click_timer = None
        if name in self.checked:
            self.checked.discard(name)
        else:
            self.checked.add(name)
        iid = self.name_to_iid.get(name)
        if iid:
            self.tree.set(iid, "sel", CHECKED if name in self.checked else UNCHECKED)

    def _open_pypi(self, name):
        webbrowser.open(f"https://pypi.org/project/{name}/")
        threading.Thread(target=self._load_description, args=(name,), daemon=True).start()

    def _load_description(self, name):
        text = self.descriptions.fetch_full(name)
        self.root.after(0, lambda: self._description_window(name, text))

    def _description_window(self, name, text):
        win = tk.Toplevel(self.root)
        win.title(f"{name} — описание (PyPI)")
        win.geometry("600x420")
        win.transient(self.root)

        url = f"https://pypi.org/project/{name}/"
        ttk.Label(win, text=url, foreground="#1a5fb4", cursor="hand2").pack(anchor=tk.W, padx=8, pady=(6, 0))

        body = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        body.insert(tk.END, text or "(нет описания)")
        body.configure(state=tk.DISABLED)

        ttk.Button(win, text="Открыть на PyPI", command=lambda: webbrowser.open(url)).pack(pady=(0, 8))

    def fetch_descriptions(self, names):
        total = len(names)
        done = 0
        lock = threading.Lock()
        max_threads = 8
        sem = threading.Semaphore(max_threads)

        def worker(name):
            nonlocal done
            with sem:
                self.descriptions.fetch(name)
                with lock:
                    done += 1
                    current = done
                self.root.after(0, lambda c=current: self.status.set(f"Загрузка описаний: {c}/{total}"))
                self.root.after(0, self._refresh_descriptions)

        threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.root.after(0, lambda: self.status.set(f"Пакетов: {len(self.packages)}"))

    def _refresh_descriptions(self):
        for iid in self.tree.get_children():
            name = self.tree.item(iid, "values")[1]
            self.tree.set(iid, "desc", self.descriptions.get(name))

    def _visible_names(self):
        return {self.tree.item(iid, "values")[1] for iid in self.tree.get_children()}

    def _selected_names(self):
        visible = self._visible_names()
        return [n for n in self.checked if n in visible]

    def _select_all_visible(self):
        self.checked.update(self._visible_names())
        self._render_checks()

    def _clear_selection(self):
        self.checked.clear()
        self._render_checks()

    def uninstall_selected(self):
        names = self._selected_names()
        if not names:
            messagebox.showinfo("Удаление", "Отметьте пакеты для удаления (чекбокс слева).")
            return
        if not messagebox.askyesno("Подтверждение", f"Удалить {len(names)} пакет(ов)?\n" + ", ".join(names[:10]) + ("..." if len(names) > 10 else "")):
            return
        self._run_uninstall(names)

    def uninstall_all(self):
        names = [p["name"] for p in self.packages]
        if not names:
            return
        if not messagebox.askyesno("Подтверждение", f"Удалить ВСЕ пакеты ({len(names)})? Действие необратимо!"):
            return
        self._run_uninstall(names)

    def _run_uninstall(self, names):
        self.status.set("Удаление...")
        self.root.update_idletasks()

        def work():
            ok, output = pip_wrapper.uninstall_packages(names)
            self.root.after(0, lambda: self._on_done(ok, output))

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, ok, output):
        if ok:
            messagebox.showinfo("Готово", "Операция завершена.")
        else:
            messagebox.showerror("Ошибка", output)
        self.refresh()
