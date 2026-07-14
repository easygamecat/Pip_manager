import logging
import os
import sys
import threading
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from src.core import pip_wrapper, pypi

logger = logging.getLogger(__name__)

CHECKED = "☑"
UNCHECKED = "☐"


class PipManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Менеджер pip-пакетов")
        self.root.geometry("820x560")

        self.descriptions = pypi.DescriptionService()
        self.packages = []
        self.outdated = {}
        self.row_packages = {}
        self.name_to_iid = {}
        self.checked = set()
        self._click_timer = None
        self.python = sys.executable

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        env = pip_wrapper.get_environment_info(self.python)
        env_text = (
            f"Python {env['version']}  |  "
            f"{'venv' if env['is_venv'] else 'системный'}  |  {env['executable']}"
        )
        env_frame = ttk.Frame(self.root)
        env_frame.pack(fill=tk.X, padx=8, pady=(8, 0))

        ttk.Label(env_frame, text="Pip Manager", font=(None, 12, "bold")).pack(side=tk.LEFT)
        ttk.Label(env_frame, text=env_text, foreground="#555").pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(env_frame, text="Окружение:").pack(side=tk.LEFT, padx=(12, 0))
        self.python_var = tk.StringVar(value=self.python)
        self.python_combo = ttk.Combobox(env_frame, textvariable=self.python_var, width=50, state="readonly")
        interpreters = pip_wrapper.find_python_interpreters()
        self.python_combo["values"] = interpreters
        if interpreters:
            if self.python not in interpreters:
                self.python = interpreters[0]
            self.python_var.set(self.python)
        self.python_combo.pack(side=tk.LEFT, padx=6)
        self.python_combo.bind("<<ComboboxSelected>>", lambda _: self._on_python_changed())
        ttk.Button(env_frame, text="Обновить окружение", command=self._reload_pythons).pack(side=tk.LEFT, padx=6)

        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=8, pady=8)

        ttk.Button(toolbar, text="Обновить", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Удалить выбранные", command=self.uninstall_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Удалить все", command=self.uninstall_all).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Обновить выбранные", command=self.update_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Обновить все", command=self.update_all).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Экспорт requirements", command=self.export_requirements).pack(side=tk.LEFT, padx=6)

        self.status = tk.StringVar(value="Готово")
        ttk.Label(toolbar, textvariable=self.status).pack(side=tk.RIGHT)
        self.progress = ttk.Progressbar(toolbar, mode="determinate", length=140)
        self.progress.pack(side=tk.RIGHT, padx=8)
        ttk.Button(toolbar, text="Лог", command=self._open_log).pack(side=tk.RIGHT, padx=6)

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
        self.tree.heading("name", text="Пакет", command=lambda: self._on_sort("name"))
        self.tree.heading("version", text="Версия", command=lambda: self._on_sort("version"))
        self.tree.heading("desc", text="Описание", command=lambda: self._on_sort("desc"))
        self.tree.column("sel", width=30, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=200, stretch=False)
        self.tree.column("version", width=90, stretch=False)
        self.tree.column("desc", stretch=True)
        self.tree.tag_configure("outdated", foreground="#c00000")
        self._last_sort_column = None
        self._last_sort_reverse = False

        tree_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(body, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))

        group_container = ttk.Frame(right)
        group_container.pack(fill=tk.BOTH, expand=True)
        ttk.Label(group_container, text="Группы (>1 пакета)").pack(anchor=tk.W)
        self.group_list = tk.Listbox(group_container)
        group_scroll = ttk.Scrollbar(group_container, orient=tk.VERTICAL, command=self.group_list.yview)
        self.group_list.configure(yscrollcommand=group_scroll.set)
        self.group_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        group_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.group_list.bind("<<ListboxSelect>>", self._on_group_select)

        details_frame = ttk.LabelFrame(right, text="Детали пакета")
        details_frame.pack(fill=tk.X, pady=(6, 0))
        self.details_name = tk.StringVar(value="(не выбран)")
        self.details_version = tk.StringVar(value="")
        ttk.Label(details_frame, textvariable=self.details_name, font=(None, 10, "bold")).pack(anchor=tk.W, padx=6, pady=(6, 0))
        ttk.Label(details_frame, textvariable=self.details_version).pack(anchor=tk.W, padx=6)
        self.details_desc = tk.StringVar(value="")
        ttk.Label(details_frame, textvariable=self.details_desc, wraplength=280, justify=tk.LEFT).pack(anchor=tk.W, padx=6, pady=(4, 0), fill=tk.X)
        actions = ttk.Frame(details_frame)
        actions.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(actions, text="Обновить", command=self._update_current).pack(side=tk.LEFT)
        ttk.Button(actions, text="Удалить", command=self._uninstall_current).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text="На PyPI", command=self._open_current_pypi).pack(side=tk.LEFT)

        self.current_name = None
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.family_iids = {}

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Delete>", lambda _: self.uninstall_selected())
        self.tree.bind("<Control-a>", lambda _: self._select_all_visible())

    def _reload_pythons(self):
        interpreters = pip_wrapper.find_python_interpreters()
        current = self.python_var.get()
        self.python_combo["values"] = interpreters
        if interpreters:
            if current not in interpreters:
                current = interpreters[0]
            self.python_var.set(current)
            self.python = current
        self.refresh()

    def _on_python_changed(self):
        self.python = self.python_var.get()
        self.refresh()

    def refresh(self):
        self.status.set("Загрузка списка...")
        self.progress.config(value=0)
        self.root.update_idletasks()

        def work():
            try:
                self.packages = pip_wrapper.get_installed_packages(self.python)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
                self.root.after(0, lambda: self.status.set("Ошибка"))
                return
            self.root.after(0, self._apply_filter)
            self.root.after(0, lambda: self.root.after(50, self._load_visible_descriptions))
            self.root.after(0, lambda: threading.Thread(target=self._load_outdated, daemon=True).start())

        threading.Thread(target=work, daemon=True).start()

    def _load_outdated(self):
        try:
            self.outdated = pip_wrapper.get_outdated(self.python)
        except Exception:
            self.outdated = {}
        self.root.after(0, self._apply_filter)

    def _load_visible_descriptions(self):
        names = self._visible_names()
        if not names:
            return
        missing = [n for n in names if not self.descriptions.get(n)]
        if not missing:
            return
        self.root.after(0, lambda: threading.Thread(
            target=self._fetch_many, args=(missing,), daemon=True
        ).start())

    def _fetch_many(self, names):
        total = len(names)
        done = 0
        lock = threading.Lock()
        max_threads = 6
        sem = threading.Semaphore(max_threads)

        def worker(name):
            nonlocal done
            with sem:
                self.descriptions.fetch(name)
                with lock:
                    done += 1
                    current = done
                self.root.after(0, lambda c=current: self.status.set(f"Описаний: {c}/{total}"))
                self.root.after(0, lambda c=current: self.progress.config(value=c))
                self.root.after(0, self._refresh_descriptions)

        self.root.after(0, lambda: self.progress.config(maximum=total, value=0))
        threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.root.after(0, lambda: self.progress.config(value=total))
        self.root.after(0, lambda: self.status.set(f"Пакетов: {len(self.packages)}"))

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
                version = pkg["version"]
                if name in self.outdated and self.outdated[name]:
                    version = f"{version} → {self.outdated[name]}"
                iid = self.tree.insert("", tk.END, values=(
                    mark, name, version, self.descriptions.get(name),
                ), tags=("outdated",) if (name in self.outdated and self.outdated[name]) else ())
                self.row_packages[iid] = [name]
                self.name_to_iid[name] = iid
                iids.append(iid)
            self.family_iids[fam] = iids

        self.status.set(f"Пакетов: {len(self.packages)}  |  групп >1: {len(multi_families)}  |  показано: {len(self.tree.get_children())}")

    def _on_sort(self, column):
        if self._last_sort_column == column:
            self._last_sort_reverse = not self._last_sort_reverse
        else:
            self._last_sort_column = column
            self._last_sort_reverse = False
        self._apply_sort()
        self._apply_filter()

    def _apply_sort(self):
        if not self._last_sort_column:
            return
        column = self._last_sort_column
        reverse = self._last_sort_reverse
        items = []
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            tags = self.tree.item(iid, "tags")
            name = values[1]
            items.append((iid, values, tags))
        col_index = {"sel": 0, "name": 1, "version": 2, "desc": 3}[column]

        def sort_key(item):
            val = item[1][col_index]
            if column == "version":
                return (0, val)
            return (0, str(val).lower())

        items.sort(key=sort_key, reverse=reverse)
        for idx, (iid, values, tags) in enumerate(items):
            self.tree.move(iid, "", idx)

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

    def _on_tree_select(self, _):
        selected = self.tree.selection()
        if not selected:
            self.current_name = None
            self.details_name.set("(не выбран)")
            self.details_version.set("")
            self.details_desc.set("")
            return
        iid = selected[0]
        values = self.tree.item(iid, "values")
        if len(values) < 2:
            return
        name = values[1]
        self.current_name = name
        self.details_name.set(name)
        self.details_version.set(values[2])
        self.details_desc.set(self.descriptions.get(name) or values[3] if len(values) > 3 else "")

    def _update_current(self):
        if not self.current_name:
            messagebox.showinfo("Обновление", "Сначала выберите пакет.")
            return
        if self.current_name not in self.outdated:
            messagebox.showinfo("Обновление", f"{self.current_name} уже актуальный.")
            return
        self._run_task("Обновление", [self.current_name], lambda ns: pip_wrapper.update_packages(ns, self.python))

    def _uninstall_current(self):
        if not self.current_name:
            messagebox.showinfo("Удаление", "Сначала выберите пакет.")
            return
        self._run_task("Удаление", [self.current_name], lambda ns: pip_wrapper.uninstall_packages(ns, self.python))

    def _open_current_pypi(self):
        if not self.current_name:
            return
        webbrowser.open(f"https://pypi.org/project/{self.current_name}/")

    def _open_pypi(self, name):
        threading.Thread(target=self._load_description, args=(name,), daemon=True).start()

    def _load_description(self, name):
        info = self.descriptions.get_info(name)
        self.root.after(0, lambda: self._description_window(name, info))

    def _description_window(self, name, info):
        win = tk.Toplevel(self.root)
        win.title(f"{name} — описание (PyPI)")
        win.geometry("640x520")
        win.transient(self.root)

        url = f"https://pypi.org/project/{name}/"
        ttk.Label(win, text=url, foreground="#1a5fb4", cursor="hand2").pack(anchor=tk.W, padx=8, pady=(6, 0))

        body = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def insert_section(title, text):
            if not text:
                return
            body.insert(tk.END, title + "\n", "section")
            body.insert(tk.END, text + "\n\n")

        body.tag_configure("section", font=(body.cget("font"), 10, "bold"))

        insert_section("Описание", info.get("summary", ""))
        insert_section("Лицензия", info.get("license", ""))
        insert_section("Домашняя страница", info.get("home_page", ""))
        requires = info.get("requires_dist") or []
        if requires:
            insert_section("Зависимости", "\n".join(requires[:50]))
        project_urls = info.get("project_urls") or {}
        if project_urls:
            urls = "\n".join(f"{k}: {v}" for k, v in project_urls.items())
            insert_section("Ссылки", urls)
        insert_section("Полное описание", info.get("description", ""))

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
                self.root.after(0, lambda c=current: self.progress.config(value=c))
                self.root.after(0, self._refresh_descriptions)

        self.root.after(0, lambda: self.progress.config(maximum=total, value=0))
        threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.root.after(0, lambda: self.progress.config(value=total))
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

    def _run_task(self, title, names, worker):
        if not names:
            messagebox.showinfo(title, "Сначала выберите пакеты.")
            return
        if not messagebox.askyesno("Подтверждение", f"{title}: {len(names)} пакет(ов)?\n" + ", ".join(names[:10]) + ("..." if len(names) > 10 else "")):
            return
        self.status.set(f"{title}...")
        self.progress.config(value=0)
        self.root.update_idletasks()

        def work():
            ok, output = worker(names)
            self.root.after(0, lambda: self._on_done(ok, output, title, names))

        threading.Thread(target=work, daemon=True).start()

    def uninstall_selected(self):
        self._run_task("Удаление", self._selected_names(), lambda ns: pip_wrapper.uninstall_packages(ns, self.python))

    def uninstall_all(self):
        names = [p["name"] for p in self.packages]
        self._run_task("Удаление всех", names, lambda ns: pip_wrapper.uninstall_packages(ns, self.python))

    def update_selected(self):
        names = [n for n in self._selected_names() if n in self.outdated]
        self._run_task("Обновление", names, lambda ns: pip_wrapper.update_packages(ns, self.python))

    def update_all(self):
        names = list(self.outdated.keys())
        self._run_task("Обновление всех", names, lambda ns: pip_wrapper.update_packages(ns, self.python))

    def export_requirements(self):
        if not self.packages:
            messagebox.showinfo("Экспорт", "Список пакетов пуст.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="requirements.txt",
        )
        if not path:
            return
        ok, out = pip_wrapper.export_requirements(self.packages, path)
        if ok:
            messagebox.showinfo("Экспорт", f"requirements.txt сохранён:\n{out}")
        else:
            messagebox.showerror("Ошибка", str(out))

    def _open_log(self):
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pip_manager.log")
        if not os.path.exists(log_path):
            messagebox.showinfo("Лог", "Файл лога ещё не создан.")
            return
        try:
            os.startfile(log_path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть лог:\n{e}")

    def _on_done(self, ok, output, title, updated_names=None):
        if ok:
            messagebox.showinfo("Готово", f"{title} завершено.")
        else:
            messagebox.showerror("Ошибка", output)
        if updated_names and any(n.lower() == "pip" for n in updated_names):
            self.root.after(1500, lambda: self._recheck_pip_outdated())
        else:
            self.refresh()

    def _recheck_pip_outdated(self, attempt=1):
        if attempt > 5:
            self.refresh()
            return
        try:
            outdated = pip_wrapper.get_outdated(self.python)
            if "pip" not in outdated:
                self.outdated = outdated
                self._apply_filter()
                return
        except Exception:
            pass
        self.root.after(1500, lambda: self._recheck_pip_outdated(attempt + 1))
