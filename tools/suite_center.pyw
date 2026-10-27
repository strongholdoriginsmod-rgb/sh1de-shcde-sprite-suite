"""Unified setup, workshop, BC7 production and tool catalog interface."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
import queue
import threading
from pathlib import Path
import sys
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'src'))
from stronghold_europe_de.sdk_toolchain import find_dotnet_sdk, resolve_dotnet_directory
from stronghold_europe_de.suite_setup import (
    inspect_toolchain_hints, normalized_games, read_game_path_hints,
)
from stronghold_europe_de.unity_toolchain import standard_unity_editor_paths
from suite_catalog import describe, describe_parser, tokens_for
from suite_usability import ScrollableColumn

loader=importlib.machinery.SourceFileLoader('original_sprite_workshop',str(ROOT/'tools/suite.pyw'))
spec=importlib.util.spec_from_loader(loader.name,loader)
workshop=importlib.util.module_from_spec(spec)
loader.exec_module(workshop)
workshop.PYTHON = Path(sys.executable)


def entry(parent,label,default='',file=False):
    row=ttk.Frame(parent)
    row.pack(fill='x',pady=5)
    ttk.Label(row,text=label,width=24).pack(side='left')
    var=tk.StringVar(value=default)
    ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
    def choose():
        value=filedialog.askopenfilename(parent=parent) if file else filedialog.askdirectory(parent=parent)
        if value: var.set(value)
    ttk.Button(row,text='…',width=3,command=choose).pack(side='left',padx=(8,0))
    return var


class Center(workshop.Suite):
    def __init__(self):
        super().__init__()
        self._original_path=os.environ.get('PATH','')
        self._original_unity=os.environ.get('STRONGHOLD_EUROPE_UNITY_EDITOR')
        self.title('SH1DE → SHCDE · Sprite Suite')
        self.geometry(f'{min(1320,self.winfo_screenwidth()-70)}x{min(900,self.winfo_screenheight()-110)}')
        self.minsize(1020,680)
        self.console.configure(height=7)
        self.console.master.pack_configure(side='bottom',before=self.notebook)
        self.setup_page=ttk.Frame(self.notebook,padding=18)
        self.bc7_page=ttk.Frame(self.notebook,padding=18)
        self.catalog_page=ttk.Frame(self.notebook,padding=18)
        self.notebook.insert(0,self.setup_page,text='Einrichten')
        self.notebook.add(self.bc7_page,text='BC7 & Pakete')
        self.notebook.add(self.catalog_page,text='Alle Werkzeuge')
        self.command_bar=ttk.Frame(self)
        self.command_bar.pack(before=self.notebook,fill='x',padx=18,pady=(0,6))
        self.build_setup()
        self.build_bc7()
        self.build_catalog()
        self.advanced = tk.BooleanVar(value=False)
        self.basic_tabs = (self.setup_page, self.tab_art, self.bc7_page)
        self.extra_tabs = tuple(tab for tab in self.notebook.tabs() if tab not in {str(t) for t in self.basic_tabs})
        switch = ttk.Checkbutton(self.command_bar, text='Erweiterte Werkzeuge', variable=self.advanced, command=self.show_advanced)
        switch.pack(side='right')
        self.tab_art.source.set('stronghold1')
        self.notebook.insert(1, self.tab_art, text='Sprites bearbeiten')
        self.notebook.insert(2, self.bc7_page, text='Paket bauen')
        self.show_advanced()
        self.notebook.select(self.setup_page)

    def show_advanced(self):
        visible = self.advanced.get()
        for tab in self.extra_tabs:
            self.notebook.tab(tab, state='normal' if visible else 'hidden')
        if visible:
            self.advanced_build.pack(fill='both', expand=True, pady=12)
        else:
            self.advanced_build.pack_forget()
            if self.notebook.select() in self.extra_tabs:
                self.notebook.select(self.setup_page)
        choices = list(self.profile_names)
        if visible:
            choices.extend(p.stem for p in sorted((ROOT/'profiles').glob('*.json'))
                           if p.stem not in self.profile_names.values())
        self.profile_picker.configure(values=choices)
        current = self.bc7_profile.get()
        label = next((name for name, value in self.profile_names.items() if value == current), current)
        if label not in choices:
            label = next(iter(self.profile_names))
            self.bc7_profile.set(self.profile_names[label])
        self.profile_choice.set(label)

    def open_tab(self, tab):
        if hasattr(self, 'extra_tabs') and str(tab) in self.extra_tabs and not self.advanced.get():
            self.advanced.set(True)
            self.show_advanced()
        super().open_tab(tab)

    def sprite_profile_path(self):
        return 'profiles/' + self.bc7_profile.get() + '.json'

    def select_profile(self, _event=None):
        selected = self.profile_choice.get()
        self.bc7_profile.set(self.profile_names.get(selected, selected))

    def prepare_games(self):
        self.tool('suite_workflow.py', ['prepare'])

    def open_output(self):
        from stronghold_europe_de.config import load_config
        try:
            config = load_config(ROOT/'config/installations.local.toml')
            path = config.output.dist_dir / self.bc7_profile.get() / config.output.mod_folder_name
            if not path.is_dir():
                messagebox.showinfo('Ausgabe', 'Bitte zuerst das Paket bauen.', parent=self)
                return
            os.startfile(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Ausgabe', str(exc), parent=self)

    def run(self,args,label):
        self.load_environment()
        return super().run(args,label)

    def run_captured(self,args,label,on_output):
        self.load_environment()
        return super().run_captured(args,label,on_output)

    def load_environment(self):
        """Rebuild tool hints per job, avoiding stale SDK/Unity paths."""
        os.environ['PATH']=getattr(self,'_original_path',os.environ.get('PATH',''))
        original=getattr(self,'_original_unity',None)
        if original is None:
            os.environ.pop('STRONGHOLD_EUROPE_UNITY_EDITOR',None)
        else:
            os.environ['STRONGHOLD_EUROPE_UNITY_EDITOR']=original
        settings,warnings=inspect_toolchain_hints(ROOT)
        if settings.get('unity_editor'):
            editor=Path(settings['unity_editor'])
            if editor.is_file():
                os.environ['STRONGHOLD_EUROPE_UNITY_EDITOR']=str(editor)
            else:
                warnings+=('Gespeicherter Unity-Pfad ist nicht mehr vorhanden.',)
        if settings.get('dotnet_directory'):
            try:
                directory=str(resolve_dotnet_directory(
                    Path(settings['dotnet_directory'])
                ))
            except (OSError,ValueError,RuntimeError) as exc:
                warnings+=(f'Gespeicherter SDK-Pfad ist nicht nutzbar: {exc}',)
            else:
                os.environ['PATH']=directory+os.pathsep+os.environ['PATH']
        if warnings and hasattr(self,'setup_save_status'):
            self.setup_save_status.set(' '.join(warnings))
        return warnings

    def tool(self,name,args=()):
        self.run([str(ROOT/'tools'/name),*args],name)

    def cli(self,*args):
        self.run(['-m','stronghold_europe_de',*args],' '.join(args))

    def build_setup(self):
        self.setup_scroller=ScrollableColumn(self.setup_page,background=workshop.BG)
        self.setup_scroller.pack(fill='both',expand=True)
        page=self.setup_scroller.body
        ttk.Label(page,text='Sprite Suite einrichten',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(page,text='Spielordner und Werkzeuge auswählen, Pfade speichern und mit den Sprites beginnen.',wraplength=950).pack(anchor='w',pady=(8,18))
        defaults,game_warnings=read_game_path_hints(ROOT)
        settings,toolchain_warnings=inspect_toolchain_hints(ROOT)
        # Extra JSON fields must not override actual game folder selections.
        defaults.update({
            key:settings[key] for key in ('unity_editor','dotnet_directory')
            if key in settings
        })
        setup_warnings=game_warnings+toolchain_warnings
        if not defaults.get('unity_editor'):
            defaults['unity_editor']=next((str(path) for path in standard_unity_editor_paths('2021.3.45f2') if path.is_file()),'')
        if not defaults.get('dotnet_directory'):
            sdk=find_dotnet_sdk(ROOT)
            if sdk:
                defaults['dotnet_directory']=str(sdk)
        self.source=entry(page,'Stronghold 1 DE',defaults.get('source',''))
        self.target=entry(page,'Crusader DE',defaults.get('target',''))
        self.unity=entry(page,'Unity 2021.3.45f2',defaults.get('unity_editor',''),file=True)
        self.dotnet=entry(page,'.NET SDK (8 oder neuer)',defaults.get('dotnet_directory',''))
        row=ttk.Frame(page);row.pack(fill='x',pady=16)
        for label,fn in [('Pfade speichern',self.save_config),('Einrichtungsstatus',self.show_setup_diagnostics),('Einrichtung prüfen',lambda:self.tool('suite_workflow.py',['check'])),('Spiele einlesen',self.prepare_games)]:
            ttk.Button(row,text=label,command=fn).pack(side='left',padx=(0,8))
        self.setup_save_status=tk.StringVar(
            value=(' '.join(setup_warnings) if setup_warnings
                   else 'Werkzeugpfade sind auch ohne Spielinstallation einzeln speicherbar.')
        )
        ttk.Label(page,textvariable=self.setup_save_status,wraplength=925).pack(
            anchor='w',fill='x',pady=(0,7)
        )
        ttk.Label(page,text='Einmal Spiele einlesen, dann Sprites bearbeiten und Paket bauen.\nDas fertige Paket liegt im Ausgabeordner. Den fertigen Modordner kannst du anschließend ins Spiel kopieren.',wraplength=950).pack(anchor='w',pady=15)
        ttk.Label(page,text='Der vorhandene Script Extender wird beim Bauen verwendet und nicht verändert.',wraplength=950).pack(anchor='w',pady=6)
        row=ttk.Frame(page);row.pack(fill='x',pady=4)
        ttk.Button(row,text='.NET SDK herunterladen',command=lambda:webbrowser.open('https://dotnet.microsoft.com/download/dotnet/10.0')).pack(side='left',padx=(0,8))
        ttk.Button(row,text='Anleitung öffnen',command=lambda:os.startfile(ROOT/'docs/EINRICHTEN.md')).pack(side='left')
        self.setup_scroller.bind_mousewheel()

    def save_config(self):
        """Keep tool-only saves available and explicitly confirm game-path changes."""
        from stronghold_europe_de.config import load_config
        if self.runner.busy:
            messagebox.showinfo(
                'Pfade speichern', 'Ein anderes Werkzeug läuft noch. '
                'Nach Abschluss können die Pfade gespeichert werden.', parent=self
            )
            return
        source=self.source.get().strip()
        target=self.target.get().strip()
        unity=self.unity.get().strip()
        dotnet=self.dotnet.get().strip()
        args=['configure']
        if unity: args.extend(['--unity',unity])
        if dotnet: args.extend(['--dotnet',dotnet])
        old_file=ROOT/'config/installations.local.toml'
        saved=None
        if old_file.exists():
            try:
                saved=load_config(old_file)
            except (OSError,ValueError,TypeError,KeyError):
                # Both game paths may be used to repair an invalid configuration.
                saved=None

        if source or target:
            try:
                if not source and saved is None:
                    raise ValueError('SH1DE-Spielpfad fehlt.')
                if not target and saved is None:
                    raise ValueError('SHCDE-Spielpfad fehlt.')
                first,game_root,game_data=normalized_games(
                    Path(source) if source else saved.source.data_dir,
                    Path(target) if target else saved.target.game_dir,
                )
            except (OSError,ValueError) as exc:
                if unity or dotnet:
                    if not messagebox.askyesno(
                        'Nur Werkzeugpfade speichern?',
                        f'Die Spielpfade sind noch unvollständig: {exc}\n\n'
                        'Unity und .NET trotzdem separat speichern? '
                        'Die Spielkonfiguration bleibt unverändert.',
                        icon='warning',default='no',parent=self,
                    ):
                        self.setup_save_status.set('Speichern abgebrochen; keine Änderungen.')
                        return
                    self.setup_save_status.set(
                        'Spielpfade noch nicht vollständig; nur Werkzeugpfade werden gespeichert.'
                    )
                else:
                    messagebox.showwarning(
                        'Spielpfade unvollständig',
                        f'{exc}\n\nBeide Spiele auswählen. '
                        'Unity/.NET können auch ohne Spiele separat gespeichert werden.',
                        parent=self,
                    )
                    self.setup_save_status.set('Spielpfade noch nicht gespeichert.')
                    return
            else:
                changed=(
                    saved is None or saved.source.data_dir!=first
                    or saved.target.game_dir!=game_root
                    or saved.target.data_dir!=game_data
                )
                if old_file.exists() and changed:
                    if not messagebox.askyesno(
                        'Gespeicherte Spielpfade ändern?',
                        'Die bereits gespeicherten Spielpfade werden geändert '
                        'oder eine ungültige Einstellung wird repariert.\n\n'
                        'Die alte Datei wird zuvor separat gesichert. '
                        'Pakete und Spielinstallationen bleiben unverändert.\n\n'
                        'Neue Spielordner wirklich übernehmen?',
                        icon='warning',default='no',parent=self,
                    ):
                        self.setup_save_status.set('Alte Spielpfade beibehalten.')
                        return
                    args.append('--replace')
                if source: args.extend(['--source',source])
                if target: args.extend(['--target',target])
        _, tool_warnings=inspect_toolchain_hints(ROOT)
        if tool_warnings and (unity or dotnet):
            if messagebox.askyesno(
                'Werkzeugkonfiguration gesichert reparieren?',
                '\n'.join(tool_warnings) + '\n\n'
                'Die beschädigte Originaldatei wird als .bak-Datei gesichert. '
                'Nur die gewählten Werkzeugpfade werden neu gespeichert.\n\n'
                'Reparatur ausdrücklich durchführen?',
                icon='warning',default='no',parent=self,
            ):
                args.append('--repair-toolchain')
            else:
                # Refusing repair does not prevent an independently valid
                # game-path change from being saved.
                filtered=['configure']
                index=1
                while index<len(args):
                    if args[index] in ('--unity','--dotnet'):
                        index+=2
                    else:
                        filtered.append(args[index])
                        index+=1
                args=filtered
                if len(args)==1:
                    self.setup_save_status.set(
                        'Alte Werkzeugkonfiguration erhalten; keine Änderung.'
                    )
                    return
        if len(args)==1:
            messagebox.showinfo(
                'Pfade speichern',
                'Bitte wenigstens einen Spielordner oder einen Unity-/.NET-Pfad wählen.',
                parent=self,
            )
            return
        self.setup_save_status.set(
            'Speicherauftrag gestartet; Ergebnis im Werkzeugprotokoll. '
            'Vor dem Bau die Voraussetzungen erneut prüfen.'
        )
        self.tool('suite_bridge.py',args)

    def show_setup_diagnostics(self):
        """Read-only setup overview; independent of BC7 build readiness."""
        from stronghold_europe_de.suite_setup import diagnose_local_setup
        report=diagnose_local_setup(ROOT)
        self.setup_save_status.set(
            f"Einrichtungsstatus: {report['warning_count']} Warnungen, "
            f"{report['notice_count']} Hinweise. Keine Dateien verändert."
        )
        lines=['Es wurden keine Dateien verändert.',
               'Kein Build oder Release bestätigt.', '']
        for item in report['checks']:
            lines.extend((
                f"[{item['state'].upper()}] {item['name']}: {item['detail']}",
                f"Nächster Schritt: {item['next_step']}", ''
            ))
        messagebox.showinfo('Einrichtungsstatus (nur lesend)',
                            '\n'.join(lines),parent=self)

    def build_bc7(self):
        self.bc7_scroller=ScrollableColumn(
            self.bc7_page,background=workshop.BG
        )
        self.bc7_scroller.pack(fill='both',expand=True)
        page=self.bc7_scroller.body
        ttk.Label(page,text='Paket bauen',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(page,text='Profil wählen → Voraussetzungen prüfen → Bau nach ausdrücklicher Bestätigung. Eine fehlgeschlagene Nachprüfung blockiert den Bauablauf.',wraplength=950).pack(anchor='w',pady=(8,12))
        self.bc7_profile=tk.StringVar(value='sprite-suite-canary-bc7-v2')
        self.profile_names={'Kleines Testpaket':'sprite-suite-canary-bc7-v2', 'Alle Spielsprites':'sprite-suite-world-bc7-v2'}
        self.profile_choice=tk.StringVar(value='Kleines Testpaket')
        ttk.Label(self.command_bar,text='Vorlage:').pack(side='left',padx=(0,8))
        self.profile_picker=ttk.Combobox(self.command_bar,textvariable=self.profile_choice,values=list(self.profile_names),state='readonly',width=28)
        self.profile_picker.pack(side='left')
        self.profile_picker.bind('<<ComboboxSelected>>',self.select_profile)
        self.replace=tk.BooleanVar(value=False)
        ttk.Checkbutton(page,text='Vorhandene Paketausgabe ersetzen',variable=self.replace).pack(anchor='w',pady=8)
        row=ttk.Frame(page);row.pack(fill='x',pady=8)
        self.build_button=ttk.Button(
            row,text='Paket bauen (mit Vorprüfung)',command=self.build_profile
        )
        self.build_button.pack(side='left',padx=(0,8))
        for label,fn in [('Ausgabe öffnen',self.open_output),
                         ('Spiel-Modordner öffnen',self.open_game_mods)]:
            ttk.Button(row,text=label,command=fn).pack(side='left',padx=(0,8))
        self.readiness_button=ttk.Button(
            row, text='Bauvoraussetzungen prüfen',
            command=self.check_build_readiness
        )
        self.readiness_button.pack(side='left',padx=(4,0))
        self.readiness_status=tk.StringVar(
            value='Bau-Bereitschaft nicht geprüft – vor dem Paketbau prüfen'
        )
        self.readiness_label=ttk.Label(
            page,textvariable=self.readiness_status,
            wraplength=850
        )
        self.readiness_label.pack(anchor='w',fill='x',pady=(0,5))
        self.build_result_status=tk.StringVar(
            value='Bauabschluss: in dieser Sitzung noch kein Paket gebaut'
        )
        result_row=ttk.Frame(page)
        result_row.pack(fill='x',pady=(0,5))
        ttk.Label(
            result_row,textvariable=self.build_result_status,wraplength=800
        ).pack(side='left',fill='x',expand=True)
        self.build_result_button=ttk.Button(
            result_row,text='Bauergebnis anzeigen',
            command=self.show_build_result,state='disabled'
        )
        self.build_result_button.pack(side='right',padx=(6,0))
        self.build_history_button=ttk.Button(
            result_row,text='Bauverlauf anzeigen',
            command=self.show_build_history
        )
        self.build_history_button.pack(side='right',padx=(6,0))
        self.build_history_status=tk.StringVar(
            value='Gespeicherter Bauverlauf wird geprüft …'
        )
        ttk.Label(
            page,textvariable=self.build_history_status,wraplength=900
        ).pack(anchor='w',fill='x',pady=(0,5))
        self._history_pending=None
        self._history_rows=[]
        self._history_open_after=False
        self._history_recheck_after=False
        self.after(350,self.refresh_build_history)
        self._build_completion_pending=None
        self._build_session=None
        self._build_last_result=None
        self._build_generation=0
        self._readiness_pending=None
        self._readiness_intent=None
        for option in (
            self.bc7_profile, self.replace, self.unity, self.dotnet,
            self.source, self.target
        ):
            option.trace_add('write',self._readiness_changed)
        ttk.Label(page,text='Den fertigen Ordner StrongholdEuropeDE bei geschlossenem Spiel nach BepInEx/plugins kopieren. Einen alten gleichnamigen Modordner vorher aus plugins herausnehmen.',wraplength=950).pack(anchor='w',pady=10)
        self.advanced_build=ttk.Frame(page)
        page=self.advanced_build
        row=ttk.Frame(page);row.pack(fill='x',pady=8)
        for label,fn in [('Inventar einzeln',lambda:self.cli('inventory','--side','both')),('Mapping einzeln',lambda:self.cli('map','propose')),('Paket prüfen',lambda:self.cli('validate','--profile-id',self.bc7_profile.get())),('Laufzeit prüfen',lambda:self.cli('runtime-validate','--profile-id',self.bc7_profile.get()))]:
            ttk.Button(row,text=label,command=fn).pack(side='left',padx=(0,8))
        ttk.Separator(page).pack(fill='x',pady=12)
        ttk.Label(page,text='UI-BC7 / inkrementeller Cache',font=('Segoe UI',13,'bold')).pack(anchor='w')
        self.ui_source=entry(page,'Quell-Modordner')
        self.ui_output=entry(page,'Neuer Ausgabeordner',str(ROOT/'work/ui-bc7-standalone/run-01'))
        row=ttk.Frame(page);row.pack(fill='x',pady=8)
        ttk.Button(row,text='UI-BC7 bauen / Cache nutzen',command=lambda:self.tool('build_ui_bc7_cache.py',['--source-mod-root',self.ui_source.get(),'--output-root',self.ui_output.get()])).pack(side='left')
        ttk.Button(row,text='UI-Kandidat zusammensetzen',command=self.compose_ui).pack(side='left',padx=8)
        ttk.Button(row,text='Cacheordner öffnen',command=self.open_cache).pack(side='left')
        self.bc7_scroller.bind_mousewheel()

    def _readiness_snapshot(self):
        return (
            self.bc7_profile.get(), bool(self.replace.get()),
            self.unity.get().strip() or None,
            self.dotnet.get().strip() or None,
            self.source.get().strip() or None,
            self.target.get().strip() or None,
        )

    def _readiness_changed(self, *_args):
        if not hasattr(self, 'readiness_status'):
            return
        if self._readiness_pending is None:
            self.readiness_status.set(
                'Auswahl geändert – Bauvoraussetzungen erneut prüfen'
            )
        else:
            self.readiness_status.set(
                'Auswahl während der Prüfung geändert – erneute Prüfung nötig'
            )

    def check_build_readiness(self, *, for_build=False):
        """Check a frozen selection; a build needs fresh results and consent."""
        if self._build_session is not None or self._build_completion_pending is not None:
            messagebox.showinfo(
                'Bauvoraussetzungen',
                'Ein Paketbau oder dessen Abschlussprüfung läuft bereits.',
                parent=self,
            )
            return
        if self._readiness_pending is not None:
            if for_build:
                messagebox.showinfo(
                    'Bauvoraussetzungen',
                    'Die Prüfung läuft bereits. Danach den Paketbau erneut wählen.',
                    parent=self,
                )
            return
        if self.runner.busy:
            messagebox.showinfo(
                'Bauvoraussetzungen',
                'Ein anderes Werkzeug läuft bereits. Bitte erst abschließen oder abbrechen.',
                parent=self,
            )
            return
        snapshot = self._readiness_snapshot()
        replies = queue.Queue(maxsize=1)
        self._readiness_pending = replies
        self._readiness_intent = 'build' if for_build else 'inspect'
        self.readiness_button.configure(state='disabled')
        self.build_button.configure(state='disabled')
        self.readiness_status.set(
            f'Prüfe Voraussetzungen für {snapshot[0]} (nur lesend) …'
        )

        def worker():
            from stronghold_europe_de.suite_build_readiness import audit_build_readiness
            try:
                result = audit_build_readiness(
                    ROOT, snapshot[0], replace=snapshot[1],
                    unity_hint=snapshot[2], dotnet_hint=snapshot[3],
                    source_hint=snapshot[4], target_hint=snapshot[5],
                )
                replies.put(('ok', snapshot, result))
            except Exception as exc:
                replies.put(('error', snapshot, str(exc)))

        threading.Thread(
            target=worker, daemon=True, name='sprite-suite-build-readiness'
        ).start()
        self.after(100, self._poll_build_readiness)

    def _poll_build_readiness(self):
        if self._readiness_pending is None:
            return
        try:
            message = self._readiness_pending.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_build_readiness)
            return
        self._readiness_pending = None
        intent = self._readiness_intent
        self._readiness_intent = None
        self.readiness_button.configure(state='normal')
        self.build_button.configure(state='normal')
        _, snapshot, payload = message
        if snapshot != self._readiness_snapshot():
            self.readiness_status.set(
                'Einstellungen während des Checks geändert – bitte erneut prüfen'
            )
            return
        if message[0] != 'ok':
            self.readiness_status.set('Bauvoraussetzungsprüfung fehlgeschlagen')
            messagebox.showerror('Bauvoraussetzungen', payload, parent=self)
            return
        self.readiness_status.set(
            f"{payload['profile_id']}: {payload['blocker_count']} Blockaden, "
            f"{payload['notice_count']} Hinweise. "
            + ('Bauversuch noch nicht möglich.' if payload['blocker_count']
               else 'Nur Voraussetzungen erfüllt; keine Releasefreigabe.')
        )
        self.log(
            f"Bauvoraussetzungen {payload['profile_id']}: "
            f"{payload['blocker_count']} Blockaden, "
            f"{payload['notice_count']} Hinweise; kein Build gestartet.",
            'bad' if payload['blocker_count'] else 'muted',
        )
        # The inspection button never starts a build. A build-button press
        # goes through the same fresh audit, then a separate explicit choice.
        if intent == 'build' and payload.get('ready_for_attempt') is True:
            self._confirm_build_profile(snapshot, payload)
        else:
            self._present_build_readiness(payload)

    def _present_build_readiness(self, result):
        """Show action-oriented prerequisites without a modal blocking wait."""
        current_language=getattr(self,"language",None)
        english=(current_language is not None and
                 str(current_language.get()).upper()=="EN")
        def tr(german,english_text):
            return english_text if english else german
        window=tk.Toplevel(self)
        window.title(tr('Bau-Bereitschaft – keine Releasefreigabe',
                        'Build readiness – not a release approval'))
        window.geometry('850x450')
        window.minsize(580,320)
        window.transient(self)
        body=ttk.Frame(window,padding=12)
        body.pack(fill='both',expand=True)
        ttk.Label(
            body,
            text=(
                f"{result['profile_id']}: {result['blocker_count']} "
                f"{'blockers' if english else 'Blockaden'}, "
                f"{result['notice_count']} "
                f"{'notices' if english else 'Hinweise'}"
            ),
            font=('Segoe UI',13,'bold'),
        ).pack(anchor='w',pady=(0,7))
        text=ScrolledText(body,wrap='word',height=15)
        text.pack(fill='both',expand=True)
        lines=[
            tr('Diese Prüfung verändert weder Profile noch Spiel, Cache oder Pakete.',
               'This check does not change profiles, game, cache or packages.'),
            tr('Sie ist keine Unity-/BC7- oder Ingame-Releasefreigabe.',
               'This is not a Unity/BC7 or in-game release certification.'),
            '',
        ]
        for item in result['checks']:
            lines.append(
                f"[{item['state'].upper()}] {item['name']}: {item['detail']}"
            )
            if item['state'] != 'ok':
                lines.append(
                    f"  {'Next step' if english else 'Nächster Schritt'}: "
                    f"{item['next_step']}"
                )
            lines.append('')
        text.insert('1.0','\n'.join(lines))
        text.configure(state='disabled')
        controls=ttk.Frame(body)
        controls.pack(fill='x',pady=(9,0))
        def open_setup():
            window.destroy()
            self.open_tab(self.setup_page)
        ttk.Button(
            controls,text=tr('Zu Einrichten','Go to setup'),command=open_setup
        ).pack(side='left')
        ttk.Button(
            controls,text=tr('Schließen','Close'),command=window.destroy
        ).pack(side='right')
        window.focus_set()

    def _confirm_build_profile(self, snapshot, report):
        """Only a fresh, matching, block-free report may reach the build CLI."""
        if snapshot != self._readiness_snapshot():
            self.readiness_status.set(
                'Auswahl vor dem Paketbau geändert – neu prüfen'
            )
            return
        profile, replace, _unity, _dotnet, _source, _target = snapshot
        if not messagebox.askyesno(
            'BC7-Paketbau wirklich starten?',
            f'Profil: {profile}\n'
            f'Bestehende Paketausgabe ersetzen: {"JA" if replace else "NEIN"}\n\n'
            'Die Vorprüfung hat keine Blockaden gefunden. '
            'Das ist keine Releasefreigabe.\n\n'
            'Der folgende Vorgang kann ein bestehendes Modpaket ersetzen '
            'und längere Zeit Unity und .NET verwenden.\n'
            'Der Spiel-Modordner wird nicht automatisch installiert.\n\n'
            'Den geprüften Bauversuch wirklich starten?',
            icon='warning', default='no', parent=self,
        ):
            self.readiness_status.set(
                'Bauversuch nach Vorprüfung ausdrücklich abgebrochen'
            )
            return
        if snapshot != self._readiness_snapshot():
            self.readiness_status.set(
                'Auswahl nach Bestätigung geändert – Bau nicht gestartet'
            )
            return
        if self.runner.busy:
            messagebox.showinfo(
                'Paketbau',
                'Ein anderes Werkzeug wurde gestartet. Paketbau nicht begonnen.',
                parent=self,
            )
            return
        from stronghold_europe_de.suite_build_readiness import (
            BuildReadinessError, recheck_build_readiness_before_start
        )
        try:
            recheck_build_readiness_before_start(
                ROOT, profile, replace=replace, report=report
            )
        except (BuildReadinessError, OSError, ValueError) as exc:
            self.readiness_status.set(
                'Eingänge seit der Prüfung verändert – Paketbau blockiert'
            )
            messagebox.showwarning(
                'Paketbau nicht gestartet',
                f'{exc}\n\nBitte Bauvoraussetzungen erneut prüfen.',
                parent=self,
            )
            return
        self._launch_tracked_build(snapshot, report)

    def _launch_tracked_build(self, snapshot, report):
        """Start exactly one CLI job and register its own completion callback."""
        from stronghold_europe_de.suite_build_completion import (
            capture_build_before
        )
        profile, replace = snapshot[:2]
        if self.runner.busy or self._build_session is not None:
            messagebox.showinfo(
                'Paketbau', 'Ein Werkzeug oder Paketbau läuft bereits.',
                parent=self
            )
            return
        # The shared Tk runner can still have a previous job's "done" event
        # in its queue after that job's thread has exited. Registering our
        # completion hook now would misattribute that old exit code to the
        # new BC7 job. Do not launch until the previous event is drained.
        if not self.events.empty():
            self.readiness_status.set(
                'Vorherigen Werkzeugabschluss zunächst verarbeiten; '
                'bitte Paket bauen anschließend erneut wählen'
            )
            messagebox.showinfo(
                'Paketbau',
                'Der Abschluss des vorherigen Werkzeugs ist noch nicht '
                'verarbeitet. Bitte danach Paket bauen erneut wählen.',
                parent=self
            )
            return
        try:
            from stronghold_europe_de.suite_build_history import append_started
            before = capture_build_before(
                ROOT, profile, report['output_target']
            )
            run_id = append_started(
                ROOT, profile, before, replace=bool(replace),
                source_hashes=(
                    report['source_hashes']
                    if isinstance(report.get('source_hashes'), dict)
                    else None
                ),
            )
        except (OSError, ValueError, KeyError) as exc:
            self.readiness_status.set(
                'Bau vor dem Start blockiert – Ausgabe/Verlauf nicht sicher überprüfbar'
            )
            messagebox.showwarning(
                'Paketbau nicht gestartet',
                f'{exc}\n\nDer Bauverlauf muss zuerst sicher lesbar sein.',
                parent=self
            )
            return
        self.build_history_status.set(
            f'Bauversuch {profile} im Verlauf erfasst; '
            'Abschluss steht noch aus.'
        )
        self._build_generation += 1
        generation = self._build_generation
        self._build_session = (generation, profile, before, run_id)
        self._build_last_result = None
        self.build_result_button.configure(state='disabled')
        self.build_result_status.set(
            f'Paketbau {profile} läuft. Build und verpflichtende '
            'Validierung noch nicht abgeschlossen.'
        )
        self.readiness_status.set(
            f'Bauauftrag {profile} gestartet; Validierung muss erfolgreich sein'
        )

        def completed(exit_code):
            if completed in self.done_hooks:
                self.done_hooks.remove(completed)
            if self._build_session != (generation, profile, before, run_id):
                return
            self._build_session = None
            self._complete_tracked_build(
                generation, profile, before, int(exit_code), run_id
            )

        self.done_hooks.append(completed)
        try:
            self.tool(
                'suite_workflow.py',
                ['build','--profile-id',profile,
                 *(['--replace'] if replace else [])],
            )
        except Exception as exc:
            if completed in self.done_hooks:
                self.done_hooks.remove(completed)
            self._build_session = None
            from stronghold_europe_de.suite_build_history import (
                append_launch_failed
            )
            try:
                append_launch_failed(ROOT, run_id, profile, str(exc))
            except (OSError, ValueError) as history_exc:
                self.build_history_status.set(
                    f'Bauverlauf konnte nicht abgeschlossen werden: {history_exc}'
                )
            else:
                self.build_history_status.set(
                    f'Paketbau {profile}: Startfehler dauerhaft erfasst'
                )
                self.refresh_build_history()
            self.build_result_status.set(
                f'Paketbau {profile}: Start des Werkzeugs fehlgeschlagen.'
            )
            raise

    def _complete_tracked_build(
        self, generation, profile, before, code, run_id
    ):
        """Independent offline audit and append-only completion in a worker."""
        if generation != self._build_generation:
            return
        self.build_result_status.set(
            f'Paketbau {profile}: '
            + ('Build/Validator beendet (Code 0); SHA-256-Abgleich läuft.'
               if code == 0 else
               f'Bau/Validierung beendet mit Code {code}; keine Freigabe.')
        )
        replies = queue.Queue(maxsize=1)
        self._build_completion_pending = replies

        def worker():
            from stronghold_europe_de.suite_build_completion import (
                inspect_completed_build
            )
            from stronghold_europe_de.suite_build_history import (
                append_completed, append_inspection_failed
            )
            try:
                result = inspect_completed_build(
                    ROOT, profile, before['output'], exit_code=code,
                    before=before
                )
            except Exception as exc:
                try:
                    append_inspection_failed(
                        ROOT, run_id, profile, code, str(exc)
                    )
                except (OSError, ValueError) as history_exc:
                    replies.put((
                        'error', generation,
                        f'{exc}; Verlauf nicht gesichert: {history_exc}'
                    ))
                else:
                    replies.put(('error', generation, str(exc)))
                return
            try:
                append_completed(ROOT, run_id, profile, result)
            except (OSError, ValueError) as exc:
                replies.put(('unpersisted', generation, result, str(exc)))
            else:
                replies.put(('ok', generation, result))

        threading.Thread(
            target=worker, daemon=True,
            name='sprite-suite-post-build-integrity',
        ).start()
        self.after(100, self._poll_build_completion)

    def _poll_build_completion(self):
        if self._build_completion_pending is None:
            return
        try:
            message = self._build_completion_pending.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_build_completion)
            return
        self._build_completion_pending = None
        generation, payload = message[1:3]
        if generation != self._build_generation:
            return
        if message[0] == 'error':
            self.build_result_status.set(
                f'Bauabschluss nicht überprüfbar: {payload}. '
                'Keine Release- oder Ingame-Freigabe.'
            )
            self.log(
                f'Bauabschlussprüfer gescheitert: {payload}', 'bad'
            )
            self.refresh_build_history()
        elif message[0] == 'unpersisted':
            _tag, _generation, report, detail = message
            self._set_build_completion(report)
            self.build_result_status.set(
                self.build_result_status.get()
                + ' HISTORIE NICHT GESPEICHERT.'
            )
            self.build_history_status.set(
                f'Verlauf NICHT gespeichert: {detail}. '
                'Ein Ergebnis im Hauptfenster ist kein dauerhafter Nachweis.'
            )
            self.log(
                f'Bauverlauf nicht gespeichert: {detail}', 'bad'
            )
        else:
            self._set_build_completion(payload)
            self.refresh_build_history()

    def _set_build_completion(self, result):
        """Display the exact tracked profile and independent audit status."""
        self._build_last_result = result
        self.build_result_button.configure(state='normal')
        profile = result['profile_id']
        count = result['verified_files']
        labels = {
            'tool_failed': 'BAU / VALIDIERUNG FEHLGESCHLAGEN',
            'offline_failed': 'SHA-256-INTEGRITÄT FEHLGESCHLAGEN',
            'audit_failed': 'ABSCHLUSSPRÜFUNG FEHLGESCHLAGEN',
            'unsupported_output': 'NICHT OFFLINE VERIFIZIERT',
            'same_manifest': 'AUSGABE IDENTISCH ZUM VORHERSTAND',
            'offline_warnings': 'OFFLINE OK MIT HINWEISEN',
            'offline_ok': 'OFFLINE SHA-256 OK',
        }
        level = result['state']
        self.build_result_status.set(
            f'Bauabschluss {profile}: {labels.get(level, "UNBEKANNT")}; '
            f'{count} Ausgabedateien geprüft; '
            'Ingame-Abnahme AUSSTEHEND.'
        )
        self.log(
            f'Paketbau {profile}: {labels.get(level, "UNBEKANNT")} '
            f'(Code {result["exit_code"]}, '
            f'{result["errors"]} Fehler, {result["warnings"]} Hinweise). '
            'Keine automatische Installation; Ingame ungeprüft.',
            'ok' if level == 'offline_ok' else
            'bad' if level in ('tool_failed','offline_failed','audit_failed')
            else 'muted',
        )

    def refresh_build_history(self, *, open_after=False):
        """Verify the bounded local SHA chain off the Tk event loop."""
        if self._history_pending is not None:
            self._history_recheck_after=True
            if open_after:
                self._history_open_after=True
            return
        self._history_open_after=bool(open_after)
        responses=queue.Queue(maxsize=1)
        self._history_pending=responses
        self.build_history_status.set(
            'Lokalen Bauverlauf und SHA-256-Verkettung überprüfen …'
        )

        def worker():
            from stronghold_europe_de.suite_build_history import (
                read_build_history
            )
            try:
                runs=read_build_history(ROOT)
                responses.put(('ok', runs))
            except Exception as exc:
                responses.put(('error',str(exc)))
        threading.Thread(
            target=worker, daemon=True, name='sprite-suite-build-history'
        ).start()
        self.after(100,self._poll_build_history)

    def _poll_build_history(self):
        if self._history_pending is None:
            return
        try:
            state,payload=self._history_pending.get_nowait()
        except queue.Empty:
            self.after(100,self._poll_build_history)
            return
        self._history_pending=None
        if self._history_recheck_after:
            self._history_recheck_after=False
            self.refresh_build_history(open_after=self._history_open_after)
            return
        open_after=self._history_open_after
        self._history_open_after=False
        if state=='error':
            self._history_rows=[]
            self.build_history_status.set(
                f'Bauverlauf nicht vertrauenswürdig/lesbar: {payload}. '
                'Keine gespeicherten Bau-Erfolge anerkannt.'
            )
            self.log(f'Bauverlauf gesperrt: {payload}', 'bad')
            if open_after:
                messagebox.showwarning(
                    'Bauverlauf nicht prüfbar',
                    f'{payload}\n\nVerlauf erst prüfen/reparieren, '
                    'nichts automatisch überschreiben.',
                    parent=self
                )
            return
        self._history_rows=payload
        if not payload:
            self.build_history_status.set(
                'Gespeicherter Bauverlauf: noch kein Bauversuch aufgezeichnet'
            )
        else:
            latest=payload[0]
            self.build_history_status.set(
                f'Gespeicherter Bauverlauf: {len(payload)} Bauversuch(e). '
                f'Letzter: {latest["profile_id"]}, {latest["state"]} '
                '(historischer Stand). Aktuelle Paketintegrität gesondert prüfen; '
                'Ingame-Abnahme nicht aus dem Verlauf ableitbar.'
            )
        if open_after:
            self._present_build_history(payload)

    def show_build_history(self):
        """History is always re-read, including the hash chain, on opening."""
        self.refresh_build_history(open_after=True)

    def _present_build_history(self, runs):
        """Scrollable, read-only list with explicit unconfirmed attempts."""
        window=tk.Toplevel(self)
        window.title('Gespeicherter Bauverlauf – keine Releasefreigabe')
        # Leave room for Windows borders on a 1020x680 desktop.
        window.geometry('900x545')
        window.minsize(650,390)
        window.transient(self)
        body=ttk.Frame(window,padding=10)
        body.pack(fill='both',expand=True)
        ttk.Label(
            body,
            text=(
                f'{len(runs)} lokale Bauversuche (SHA-256-Kette geprüft). '
                'Offene Starts bleiben UNBESTÄTIGT.'
            ),
            wraplength=960,
        ).pack(anchor='w',pady=(0,8))
        grid=ttk.Frame(body)
        grid.pack(fill='both',expand=True)
        cols=('date','profile','state')
        table=ttk.Treeview(
            grid,columns=cols,show='headings',height=9,selectmode='browse'
        )
        for col,title,width in (
            ('date','Begonnen (UTC)',170),
            ('profile','Profil',290),
            ('state','Ergebnis / Nachweis',260),
        ):
            table.heading(col,text=title)
            table.column(col,width=width,stretch=col!='date')
        scrollbar=ttk.Scrollbar(
            grid,orient='vertical',command=table.yview
        )
        table.configure(yscrollcommand=scrollbar.set)
        table.pack(side='left',fill='both',expand=True)
        scrollbar.pack(side='right',fill='y')
        details=ScrolledText(body,wrap='word',height=10)
        details.pack(fill='both',expand=True,pady=(10,0))
        details.configure(state='disabled')

        for index,item in enumerate(runs):
            table.insert(
                '', 'end', iid=str(index),
                values=(
                    item['started_utc'],
                    item['profile_id'],
                    item['state'],
                )
            )

        def show_selection(_event=None):
            selected=table.selection()
            if not selected:
                return
            item=runs[int(selected[0])]
            result=item['result']
            lines=[
                f'Bauversuch-ID: {item["run_id"]}',
                f'Profil: {item["profile_id"]}',
                f'Beginn (UTC): {item["started_utc"]}',
                f'Letztes Ereignis (UTC): {item["last_utc"]}',
                f'Gespeicherter Zustand: {item["state"]}',
                f'Ersetzen gewählt: {"JA" if item["replace"] else "NEIN"}',
                '',
                'HISTORISCHER BAUVERSUCH. Die heutige Paketausgabe wurde '
                'beim Lesen des Verlaufs nicht erneut geprüft. '
                'Für den aktuellen Stand: Diagnose → Gesamten Build prüfen.',
                '',
                'Beim Start bestätigte Eingangs-SHA-256:',
                *(
                    [
                        f'- {name}: {digest}'
                        for name, digest in sorted(item['source_hashes'].items())
                    ]
                    if item.get('source_hashes') else
                    ['Keine SHA-Quellenbindungen im älteren Verlaufseintrag.']
                ),
                '',
                item['message'],
            ]
            if result is None:
                lines += [
                    '',
                    'KEIN verifizierter Abschluss gespeichert.',
                    'Ein Absturz, eine Unterbrechung oder ein Startfehler '
                    'ist kein erfolgreicher Buildnachweis.',
                ]
            else:
                lines += [
                    '',
                    f'CLI-Exitcode: {result["exit_code"]}',
                    f'Offline geprüfte Dateien: {result["verified_files"]}',
                    f'Offline-Byteumfang: {result.get("verified_bytes", 0)}',
                    f'Integritätsfehler: {result["errors"]}',
                    f'Warnungen: {result.get("warnings", 0)}',
                    f'Manifest SHA-256: '
                    f'{result.get("manifest_sha256") or "nicht bestätigt"}',
                    '',
                    'Ingame-Abnahme: AUSSTEHEND',
                    'Releasefreigabe: NEIN',
                    'Automatische Installation: NEIN',
                    '',
                    *[f'- {line}' for line in result.get('issues', [])],
                ]
            details.configure(state='normal')
            details.delete('1.0','end')
            details.insert('1.0','\n'.join(lines))
            details.configure(state='disabled')

        table.bind('<<TreeviewSelect>>',show_selection)
        if runs:
            table.selection_set('0')
            show_selection()
        control_row=ttk.Frame(body)
        control_row.pack(fill='x',pady=(8,0))
        ttk.Button(
            control_row,text='Erneut prüfen',
            command=lambda: (window.destroy(),self.show_build_history())
        ).pack(side='left')
        ttk.Button(
            control_row,text='Schließen',command=window.destroy
        ).pack(side='right')
        window.focus_set()

    def show_build_result(self):
        """Read-only details of the last actual build attempt in this session."""
        result = self._build_last_result
        if result is None:
            messagebox.showinfo(
                'Bauergebnis', 'In dieser Sitzung wurde kein Paketbau abgeschlossen.',
                parent=self
            )
            return
        window = tk.Toplevel(self)
        window.title('Paketbau-Ergebnis – Ingame-Abnahme ausstehend')
        window.geometry('870x470')
        window.minsize(600,330)
        window.transient(self)
        body = ttk.Frame(window, padding=12)
        body.pack(fill='both', expand=True)
        ttk.Label(
            body,
            text=f'{result["profile_id"]}: {result["state"]}',
            font=('Segoe UI', 13, 'bold'),
        ).pack(anchor='w', pady=(0,8))
        lines = [
            f'Profil: {result["profile_id"]}',
            f'CLI-Exitcode: {result["exit_code"]}',
            f'Offline-Status: {result["state"]}',
            result['detail'],
            f'Geprüfte Dateien: {result["verified_files"]}',
            f'Geprüfte Bytes: {result["verified_bytes"]}',
            f'Integritätsfehler: {result["errors"]}',
            f'Hinweise: {result["warnings"]}',
            f'Manifest SHA-256: {result["manifest_sha256"] or "nicht bestätigt"}',
            'Gegenüber vorherigem Manifest identisch: '
            + str(result['same_manifest_as_before']),
            '',
            'Ingame-Abnahme: AUSSTEHEND',
            'Releasefreigabe: NEIN',
            'Automatische Installation: NEIN',
            'Die offline geprüfte Ausgabe ist keine Gameplay-/Shaderfreigabe.',
            '',
            'Hinweise und Fehler:',
            *[f'- {entry}' for entry in result['issues']],
        ]
        text = ScrolledText(body, wrap='word')
        text.pack(fill='both', expand=True)
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        row = ttk.Frame(body)
        row.pack(fill='x', pady=(8,0))
        ttk.Button(
            row, text='Schließen', command=window.destroy,
        ).pack(side='right')
        window.focus_set()

    def build_profile(self):
        """Never bypass the fresh readiness and explicit consent workflow."""
        self.check_build_readiness(for_build=True)

    def open_game_mods(self):
        from stronghold_europe_de.config import load_config
        try:
            config = load_config(ROOT/'config/installations.local.toml')
            path = config.target.game_dir / 'BepInEx/plugins'
            if not path.is_dir():
                messagebox.showinfo('Spiel-Modordner', 'In der gewählten Spielinstallation fehlt BepInEx/plugins.', parent=self)
                return
            os.startfile(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Spiel-Modordner', str(exc), parent=self)

    def compose_ui(self):
        if messagebox.askyesno('UI-Kandidat','Den vorhandenen Produktionskandidaten durch das geprüfte UI-Paket ersetzen?',parent=self):
            self.tool('compose_ui_bc7_candidate.py',['--replace'])

    def open_cache(self):
        path=ROOT/'cache';path.mkdir(exist_ok=True);os.startfile(path)

    def build_catalog(self):
        page=self.catalog_page
        ttk.Label(page,text='Werkzeugkatalog',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(page,text='Sprite-, Atlas- und Projektwerkzeuge. Felder stammen aus ihren eigenen CLI-Definitionen.\nProjektgebundene Spezialwerkzeuge behalten ihre ursprünglichen Voraussetzungen.',wraplength=950).pack(anchor='w',pady=8)
        self.catalog_tool=tk.StringVar()
        names=sorted(p.name for p in (ROOT/'tools').glob('*.py') if p.name not in {'suite_catalog.py','modding_host.py'} and not p.name.startswith('shcdese_'))
        self.catalog_paths={name:ROOT/'tools'/name for name in names}
        self.catalog_paths['Installer bauen']=ROOT/'installer/build_release.py'
        self.catalog_paths['Installer prüfen']=ROOT/'installer/audit_release.py'
        self.catalog_paths['Atlasvertrag']=ROOT/'extras/atlas-contract/atlas_contract/__main__.py'
        for path in (ROOT/'extras/atlas-contract/werkzeuge').glob('*.py'):
            self.catalog_paths['Atlasmessung / '+path.name]=path
        names=['Pipeline',*self.catalog_paths]
        picker=ttk.Combobox(page,textvariable=self.catalog_tool,values=names,state='readonly',width=55)
        picker.pack(anchor='w');picker.bind('<<ComboboxSelected>>',lambda _:self.load_catalog())
        self.catalog_action=tk.StringVar()
        self.action_picker=ttk.Combobox(page,textvariable=self.catalog_action,state='readonly',width=55)
        self.action_picker.pack(anchor='w',pady=6)
        self.action_picker.bind('<<ComboboxSelected>>',lambda _:self.draw_fields())
        self.description=ttk.Label(page,text='',wraplength=860)
        self.description.pack(anchor='w',fill='x',pady=6)
        # Reserve the actual action buttons below the variable-height CLI
        # form. Packing them after an expanding canvas used to push them
        # outside the window at 1020x680 (yet still counted by older tests).
        self.catalog_footer=ttk.Frame(page)
        self.catalog_footer.pack(side='bottom',fill='x',pady=(5,0))
        self.extra=tk.StringVar()
        ttk.Label(
            self.catalog_footer,
            text='Zusätzliche Argumente (Pfade mit Leerzeichen in Anführungszeichen)',
            wraplength=750
        ).pack(anchor='w',fill='x',pady=(4,0))
        ttk.Entry(
            self.catalog_footer,textvariable=self.extra
        ).pack(fill='x',pady=(0,4))
        row=ttk.Frame(self.catalog_footer)
        row.pack(fill='x',pady=(0,4))
        self.catalog_help_button=ttk.Button(
            row,text='CLI-Hilfe anzeigen',command=self.catalog_help
        )
        self.catalog_help_button.pack(side='left')
        self.catalog_run_button=ttk.Button(
            row,text='Ausführen',command=self.catalog_run
        )
        self.catalog_run_button.pack(side='left',padx=8)
        self.catalog_field_scroll=ScrollableColumn(
            page, background=workshop.BG
        )
        self.catalog_field_scroll.pack(fill='both',expand=True)
        self.field_frame=self.catalog_field_scroll.body
        self.catalog_tool.set('sprites.py');self.load_catalog()

    def load_catalog(self):
        try:
            if self.catalog_tool.get()=='Pipeline':
                from stronghold_europe_de.cli import _parser
                self.catalog=describe_parser(_parser())
            else:self.catalog=describe(self.catalog_paths[self.catalog_tool.get()])
        except Exception as exc:messagebox.showerror('Werkzeug',str(exc),parent=self);return
        self.description.configure(text=self.catalog['description'].split('\n\n')[0])
        choices=[' '.join(c) or '(Standard)' for c in self.catalog['commands']]
        self.action_picker.configure(values=choices)
        self.catalog_action.set(choices[1] if len(choices)>1 else choices[0]);self.draw_fields()

    def draw_fields(self):
        for w in self.field_frame.winfo_children():w.destroy()
        command=tuple(self.catalog_action.get().split()) if self.catalog_action.get()!='(Standard)' else ()
        self.active_command=command
        self.active_fields=[f for f in self.catalog['fields'] if command[:len(f['command'])]==f['command']]
        self.field_values=[]
        for f in self.active_fields:
            name=' / '.join(f['names'])
            row=ttk.Frame(self.field_frame)
            row.pack(fill='x',pady=(5,1),padx=4)
            ttk.Label(row,text=name,width=26,wraplength=190).pack(
                side='left',padx=(0,8)
            )
            if f.get('action') in {'store_true','store_false'}:
                var=tk.BooleanVar(value=False)
                ttk.Checkbutton(row,variable=var).pack(side='left')
            else:
                var=tk.StringVar()
                if f.get('choices'):
                    ttk.Combobox(row,textvariable=var,values=f['choices']).pack(
                        side='left',fill='x',expand=True
                    )
                else:
                    ttk.Entry(row,textvariable=var).pack(
                        side='left',fill='x',expand=True
                    )
            self.field_values.append(var)
            if f.get('help'):
                ttk.Label(
                    self.field_frame,text=str(f['help']),
                    wraplength=650,justify='left'
                ).pack(anchor='w',fill='x',padx=12,pady=(0,3))
        self.catalog_field_scroll.bind_mousewheel()

    def catalog_help(self):
        # Help is only dispatched for argparse tools. Some historical scripts
        # have unguarded top-level writes, so never invoke them just to inspect.
        if not self.catalog['fields'] and self.catalog['commands']==[()]:
            messagebox.showinfo('Projektwerkzeug',self.catalog['description'],parent=self);return
        self.run_catalog([*self.active_command,'--help'])

    def run_catalog(self,args):
        name=self.catalog_tool.get()
        if name=='Pipeline':self.cli(*args)
        elif name=='Atlasvertrag':self.tool('atlas_contract_gui.py',args)
        else:self.run([str(self.catalog_paths[name]),*args],name)

    def catalog_run(self):
        try:args=tokens_for(self.active_command,self.active_fields,[v.get() for v in self.field_values],self.extra.get())
        except ValueError as exc:messagebox.showerror('Eingaben',str(exc),parent=self);return
        if messagebox.askyesno('Werkzeug starten',self.catalog_tool.get()+'\n'+' '.join(args)+'\n\nMit diesen Eingaben ausführen?',parent=self):
            self.run_catalog(args)


if __name__=='__main__':
    Center().mainloop()
