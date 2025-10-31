"""Tkinter-based user interface for configuring Wormhole translations."""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .translator import TranslationSummary


TranslationExecutor = Callable[..., tuple[int, Optional[TranslationSummary], Optional[str]]]
SummaryPrinter = Callable[[TranslationSummary], None]


class WormholeGUI:
    """Encapsulates the Tkinter UI and translation workflow."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        args: Any,
        translation_executor: TranslationExecutor,
        summary_printer: SummaryPrinter,
        provider_debug: bool,
    ) -> None:
        self.root = root
        self.args = args
        self.translation_executor = translation_executor
        self.summary_printer = summary_printer
        self.provider_debug = provider_debug

        self.exit_code: int = 0
        self.translation_in_progress = False
        self._has_finished = False

        self._build_variables()
        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_variables(self) -> None:
        """Initialise Tkinter control variables from CLI arguments."""

        self.input_path_var = tk.StringVar(value=getattr(self.args, "input_file", "") or "")
        self.output_path_var = tk.StringVar(value=getattr(self.args, "output", "") or "")
        self.target_language_var = tk.StringVar(
            value=getattr(self.args, "target_language", "") or ""
        )
        self.source_language_var = tk.StringVar(
            value=getattr(self.args, "source_language", "") or ""
        )
        self.provider_var = tk.StringVar(value=getattr(self.args, "provider", "") or "")
        self.model_var = tk.StringVar(value=getattr(self.args, "model", "") or "")

        batch_guidance = getattr(self.args, "batch_guidance", 2000) or 2000
        self.batch_guidance_var = tk.StringVar(value=str(batch_guidance))

        self.force_var = tk.BooleanVar(value=bool(getattr(self.args, "force", False)))
        self.non_interactive_var = tk.BooleanVar(
            value=bool(getattr(self.args, "non_interactive", False))
        )

        self.status_var = tk.StringVar(
            value="Select your document, choose a target language, then run the translation."
        )

        self.verbose_flag = bool(getattr(self.args, "verbose", False))

    def _build_ui(self) -> None:
        """Construct the Tkinter layout."""

        self.root.title("Wormhole Translator")
        #self.root.geometry("640x520")
        self.root.geometry("640x580")
        self.root.resizable(False, False)

        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Input file
        ttk.Label(main_frame, text="Input file (.docx or .pptx)").grid(
            row=0, column=0, sticky="w"
        )
        input_entry = ttk.Entry(main_frame, textvariable=self.input_path_var, width=45)
        input_entry.grid(row=1, column=0, sticky="we", pady=(0, 10))
        ttk.Button(main_frame, text="Browse…", command=self._choose_input).grid(
            row=1, column=1, padx=(10, 0), sticky="we"
        )

        # Output file
        ttk.Label(main_frame, text="Output file (optional)").grid(row=2, column=0, sticky="w")
        output_entry = ttk.Entry(main_frame, textvariable=self.output_path_var, width=45)
        output_entry.grid(row=3, column=0, sticky="we", pady=(0, 10))
        ttk.Button(main_frame, text="Browse…", command=self._choose_output).grid(
            row=3, column=1, padx=(10, 0), sticky="we"
        )

        # Target language
        ttk.Label(main_frame, text="Target language").grid(row=4, column=0, sticky="w")
        ttk.Entry(main_frame, textvariable=self.target_language_var, width=45).grid(
            row=5, column=0, sticky="we", pady=(0, 10)
        )

        # Source language
        ttk.Label(main_frame, text="Source language (optional)").grid(row=6, column=0, sticky="w")
        ttk.Entry(main_frame, textvariable=self.source_language_var, width=45).grid(
            row=7, column=0, sticky="we", pady=(0, 10)
        )

        # Provider and model
        ttk.Label(main_frame, text="Provider (optional)").grid(row=8, column=0, sticky="w")
        ttk.Entry(main_frame, textvariable=self.provider_var, width=45).grid(
            row=9, column=0, sticky="we", pady=(0, 10)
        )

        ttk.Label(main_frame, text="Model (optional)").grid(row=10, column=0, sticky="w")
        ttk.Entry(main_frame, textvariable=self.model_var, width=45).grid(
            row=11, column=0, sticky="we", pady=(0, 10)
        )

        # Batch guidance
        ttk.Label(main_frame, text="Batch guidance (characters per batch)").grid(
            row=12, column=0, sticky="w"
        )
        ttk.Entry(main_frame, textvariable=self.batch_guidance_var, width=20).grid(
            row=13, column=0, sticky="w", pady=(0, 10)
        )

        # Checkboxes
        checkbox_frame = ttk.Frame(main_frame)
        checkbox_frame.grid(row=14, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Checkbutton(
            checkbox_frame,
            text="Force overwrite existing output",
            variable=self.force_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            checkbox_frame,
            text="Non-interactive mode",
            variable=self.non_interactive_var,
        ).grid(row=1, column=0, sticky="w")

        # Status label
        ttk.Label(main_frame, textvariable=self.status_var, foreground="#555").grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(5, 15)
        )

        # Action buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=16, column=0, columnspan=2, sticky="e")

        self.start_button = ttk.Button(action_frame, text="Run translation", command=self._on_start)
        self.start_button.grid(row=0, column=0, padx=(0, 10))

        ttk.Button(action_frame, text="Cancel", command=self._on_close).grid(row=0, column=1)

        # Allow pressing Enter to trigger translation.
        self.root.bind("<Return>", self._on_start_event)

    def _choose_input(self) -> None:
        """Prompt the user to select an input document."""

        selection = filedialog.askopenfilename(
            title="Select a document",
            filetypes=[
                ("Word documents", "*.docx"),
                ("PowerPoint presentations", "*.pptx"),
                ("All files", "*.*"),
            ],
        )
        if selection:
            self.input_path_var.set(selection)

    def _choose_output(self) -> None:
        """Prompt the user to select an output path."""

        selection = filedialog.asksaveasfilename(
            title="Save translated document as",
            filetypes=[
                ("Word documents", "*.docx"),
                ("PowerPoint presentations", "*.pptx"),
                ("All files", "*.*"),
            ],
            defaultextension=".docx",
        )
        if selection:
            self.output_path_var.set(selection)

    def _on_start_event(self, event: Any) -> None:
        """Handle Return/Enter key presses."""

        self._on_start()

    def _on_start(self) -> None:
        """Gather configuration and begin the translation in a worker thread."""

        if self.translation_in_progress:
            return

        input_path = self.input_path_var.get().strip()
        target_language = self.target_language_var.get().strip()
        if not input_path:
            messagebox.showerror("Wormhole", "Please choose an input .docx or .pptx file.")
            return
        if not target_language:
            messagebox.showerror("Wormhole", "Please provide a target language.")
            return

        try:
            batch_guidance = int(self.batch_guidance_var.get())
            if batch_guidance <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Wormhole",
                "Batch guidance must be a positive integer number of characters.",
            )
            return

        output_path = self.output_path_var.get().strip() or None
        source_language = self.source_language_var.get().strip() or None
        provider = self.provider_var.get().strip() or None
        model = self.model_var.get().strip() or None

        self.translation_in_progress = True
        self.status_var.set("Running translation — please wait.")
        self.start_button.config(state="disabled")

        config = {
            "input_file": input_path,
            "output_file": output_path,
            "target_language": target_language,
            "source_language": source_language,
            "provider": provider,
            "model": model,
            "batch_guidance": batch_guidance,
            "force_overwrite": self.force_var.get(),
            "non_interactive": self.non_interactive_var.get(),
            "verbose": self.verbose_flag,
            "provider_debug": self.provider_debug,
        }

        threading.Thread(
            target=self._execute_translation,
            args=(config,),
            daemon=True,
        ).start()

    def _execute_translation(self, config: dict[str, Any]) -> None:
        """Invoke the translation executor in a worker thread."""

        exit_code, summary, message = self.translation_executor(**config)
        self.root.after(
            0,
            self._handle_result,
            exit_code,
            summary,
            message,
        )

    def _handle_result(
        self,
        exit_code: int,
        summary: Optional[TranslationSummary],
        message: Optional[str],
    ) -> None:
        """Update the UI after the translation completes."""

        self.translation_in_progress = False
        self.start_button.config(state="normal")

        if summary is not None:
            self.summary_printer(summary)

        if message:
            print(message)

        if exit_code == 0 and summary is not None:
            friendly_message = (
                "Translation finished successfully!\n"
                f"The translated document is available at:\n{summary.output_path}"
            )
            self.status_var.set("Translation complete.")
        elif message:
            friendly_message = (
                "Translation did not finish successfully.\n"
                f"{message}"
            )
            self.status_var.set("Translation ended with issues.")
        else:
            friendly_message = (
                "Translation finished with a non-zero status code. "
                "Please review the console output for details."
            )
            self.status_var.set("Translation ended with issues.")

        self.exit_code = exit_code
        self._has_finished = True

        messagebox.showinfo("Wormhole", friendly_message)
        self.root.destroy()

    def _on_close(self) -> None:
        """Handle window close requests."""

        if self.translation_in_progress:
            confirm = messagebox.askyesno(
                "Wormhole",
                "A translation is currently in progress. Do you want to stop it and exit?",
            )
            if not confirm:
                return
            self.exit_code = 2

        if not self._has_finished:
            messagebox.showinfo("Wormhole", "Thanks for using Wormhole Translator!")

        self.root.destroy()


def launch_gui(
    *,
    args: Any,
    translation_executor: TranslationExecutor,
    summary_printer: SummaryPrinter,
    provider_debug: bool,
) -> int:
    """Entry point called from the CLI when --gui is provided."""

    root = tk.Tk()
    app = WormholeGUI(
        root=root,
        args=args,
        translation_executor=translation_executor,
        summary_printer=summary_printer,
        provider_debug=provider_debug,
    )
    root.mainloop()
    return app.exit_code
