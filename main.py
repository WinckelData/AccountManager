import customtkinter as ctk
import json, os, sys, threading
from datetime import datetime
from PIL import Image

from src.ui.ui_utils import open_add_modal
from src.ui.ui_lol import render_lol_view
from src.ui.ui_sc2 import render_sc2_view
from src.config import BASE_DIR, SETTINGS_PATH
from src.data_updater import update_sc2_data
from src.sync_engine import SyncEngine


class AccountManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Game Account Manager")
        self.geometry("1100x750")
        self.minsize(900, 600)  # Prevent UI breakage when shrinking

        self.current_game = "LoL"
        self.updating = {"LoL": False, "SC2": False}
        self.update_start_times = {"LoL": 0, "SC2": 0}
        self.settings = self.load_settings()
        
        self.load_data()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # --- Assets ---
        self.img_lol_side = self.load_image("assets/lol_icon.png", (128, 128))
        self.img_sc2_side = self.load_image("assets/sc2_icon.png", (128, 128))
        self.img_lol_head = self.load_image("assets/lol_icon.png", (72, 72))
        self.img_sc2_head = self.load_image("assets/sc2_icon.png", (72, 72))

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self.sidebar, text="Games", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=30)

        # Stacked XL Buttons
        self.btn_lol = ctk.CTkButton(self.sidebar, text="League of Legends", image=self.img_lol_side,
                                     compound="top", font=ctk.CTkFont(size=14, weight="bold"),
                                     width=200, height=180, command=self.show_lol_view)
        self.btn_lol.pack(pady=10, padx=20)

        self.btn_sc2 = ctk.CTkButton(self.sidebar, text="StarCraft II", image=self.img_sc2_side,
                                     compound="top", font=ctk.CTkFont(size=14, weight="bold"),
                                     width=200, height=180, command=self.show_sc2_view)
        self.btn_sc2.pack(pady=10, padx=20)

        # Bottom Sidebar Info
        self.sidebar_bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_bottom.pack(side="bottom", fill="x", pady=20)

        self.lbl_timestamp = ctk.CTkLabel(self.sidebar_bottom, text="Last Updated: Never", text_color="gray",
                                          font=("Arial", 11))
        self.lbl_timestamp.pack()

        self.lbl_status = ctk.CTkLabel(self.sidebar_bottom, text="", text_color="gray")
        self.lbl_status.pack(pady=(5, 10))

        # Fixed height container so packing/unpacking progress bar doesn't cause jitter
        self.pb_container = ctk.CTkFrame(self.sidebar_bottom, height=20, fg_color="transparent")
        self.pb_container.pack(fill="x", pady=(0, 10), padx=20)
        self.pb_container.pack_propagate(False)

        self.btn_refresh = ctk.CTkButton(self.sidebar_bottom, text="Refresh Current Data", fg_color="#2B7A0B",
                                         hover_color="#54B435", command=self.refresh_data)
        self.btn_refresh.pack(padx=20)

        # --- Main Content ---
        self.main_frame = ctk.CTkScrollableFrame(self, corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)

        self.show_lol_view()

    # --- Helper Logic ---
    def load_image(self, rel_path, size):
        path = BASE_DIR / rel_path
        if path.exists():
            return ctk.CTkImage(Image.open(path), size=size)
        return None

    def load_data(self):
        """Correctly assigns data to class attributes so they persist."""
        from src.services.data_service import get_lol_dashboard_data, get_sc2_dashboard_data

        try:
            # Load League of Legends data via DTOs
            self.lol_data = get_lol_dashboard_data()
            
            # Load StarCraft II data via DTOs
            self.sc2_data = get_sc2_dashboard_data()
        except Exception as e:
            print(f"Error loading data from Service Layer: {e}")
            self.lol_data = []
            self.sc2_data = []

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"lol_updated": "Never", "sc2_updated": "Never"}

    def update_timestamp_display(self):
        key = "lol_updated" if self.current_game == "LoL" else "sc2_updated"
        time_str = self.settings.get(key, 'Never')
        
        display_text = f"{self.current_game} Updated:\n{time_str}"
        color = "gray"
        
        if time_str != "Never":
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                delta = datetime.now() - dt
                
                if delta.days == 0:
                    hours = int(delta.total_seconds() / 3600)
                    if hours == 0:
                        mins = int(delta.total_seconds() / 60)
                        rel_str = f"{mins} mins ago" if mins > 0 else "Just now"
                    else:
                        rel_str = f"{hours} hours ago"
                else:
                    rel_str = f"{delta.days} days ago"
                    
                display_text += f"\n({rel_str})"
                
                if delta.days >= 7:
                    color = "#cc3333"  # Red
                elif delta.days >= 1:
                    color = "#d4a017"  # Orange/Yellow
            except ValueError:
                pass
                
        self.lbl_timestamp.configure(text=display_text, text_color=color)

    def update_sidebar_state(self):
        if self.updating[self.current_game]:
            self.btn_refresh.configure(state="disabled", text=f"Updating {self.current_game}...")
        else:
            self.btn_refresh.configure(state="normal", text=f"Update {self.current_game} Data")

    def clear_status(self):
        # We only clear if it's a generic message or matches the current game's specific message to avoid clearing a newly fired status
        current_text = self.lbl_status.cget("text")
        if current_text in ["Copied!", "Update Failed"] or "Update Success!" in current_text:
            self.lbl_status.configure(text="")

    def _update_timer(self):
        """Visual timer loop while an update is running."""
        if self.updating[self.current_game]:
            import time
            elapsed = int(time.time() - self.update_start_times[self.current_game])
            mins, secs = divmod(elapsed, 60)
            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

            self.lbl_status.configure(text=f"{self.current_game} Updating... ({time_str})", text_color="#d4a017")
            self.after(1000, self._update_timer)

    # --- View Switchers ---
    def show_lol_view(self):
        self.current_game = "LoL"
        self.update_timestamp_display()
        self.update_sidebar_state()

        # Clear any frozen text from the other tab
        self.lbl_status.configure(text="")

        # Restart visual timer if we switched back to an updating tab
        if self.updating["LoL"]:
            self._update_timer()

        self.main_frame._parent_canvas.yview_moveto(0)

        # Clear references to prevent background scripts from updating dead widgets
        self.lol_row_widgets = {}
        self.sc2_row_widgets = {}

        render_lol_view(
            self.main_frame,
            self.lol_data,
            self.copy_to_clipboard,
            lambda: open_add_modal(self),  # Passing 'self' gives the utility access to app state
            self.img_lol_head,
            self.lol_row_widgets
        )
        
        if hasattr(self, 'update_status') and "LoL" in self.update_status:
            for acc_id, state in self.update_status["LoL"].items():
                if acc_id in self.lol_row_widgets:
                    w = self.lol_row_widgets[acc_id]
                    display_name = w.get('display_name', acc_id)
                    self._apply_row_style(w['card'], w['name_lbl'], display_name, state['status'], state['has_changes'])
    def show_sc2_view(self):
        """Switches to the SC2 view and refreshes the UI."""
        self.current_game = "SC2"
        self.update_timestamp_display()
        self.update_sidebar_state()

        # Clear any frozen text from the other tab
        self.lbl_status.configure(text="")

        # Restart visual timer if we switched back to an updating tab
        if self.updating["SC2"]:
            self._update_timer()

        self.main_frame._parent_canvas.yview_moveto(0)

        # Clear references to prevent background scripts from updating dead widgets
        self.sc2_row_widgets = {}
        self.lol_row_widgets = {}

        render_sc2_view(
            self.main_frame,
            self.sc2_data,
            self.copy_to_clipboard,
            lambda: open_add_modal(self),
            self.img_sc2_head,
            self.sc2_row_widgets
        )
        
        if hasattr(self, 'update_status') and "SC2" in self.update_status:
            for acc_id, state in self.update_status["SC2"].items():
                if acc_id in self.sc2_row_widgets:
                    w = self.sc2_row_widgets[acc_id]
                    display_name = w.get('display_name', acc_id)
                    self._apply_row_style(w['card'], w['name_lbl'], display_name, state['status'], state['has_changes'])

    # --- Actions ---
    def copy_to_clipboard(self, text):
        if not text:
            self.lbl_status.configure(text="No login saved!", text_color="orange")
            self.after(3000, self.clear_status)
            return

        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.lbl_status.configure(text="Copied!", text_color="white")
        self.after(3000, self.clear_status)

    def refresh_data(self):
        game_to_update = self.current_game
        if self.updating[game_to_update]:
            return
            
        import time
        self.updating[game_to_update] = True
        self.update_start_times[game_to_update] = time.time()
        self.update_sidebar_state()
        self._update_timer()
        threading.Thread(target=self._run_scripts, args=(game_to_update,), daemon=True).start()

    def _run_scripts(self, game):
        # Reset state at start of update
        if not hasattr(self, 'update_status'):
            self.update_status = {"LoL": {}, "SC2": {}}
        self.update_status[game] = {}
        
        try:
            if game == "LoL":
                engine = SyncEngine()
                engine.sync_all(progress_callback=lambda acc, st, hc, cur, tot: self._on_progress_update("LoL", acc, st, hc, cur, tot))
            else:
                update_sc2_data(progress_callback=lambda acc, st, hc, cur, tot: self._on_progress_update("SC2", acc, st, hc, cur, tot))
            self.after(0, self._on_update_success, game)
        except Exception as e:
            print(f"Update failed for {game}: {e}")
            self.after(0, self._on_update_failure, game)

    def _on_progress_update(self, game, account_id, status, has_changes, current, total):
        self.after(0, self._handle_progress_ui, game, account_id, status, has_changes, current, total)

    def _handle_progress_ui(self, game, account_id, status, has_changes, current, total):
        # 1. Update State dictionary
        if not hasattr(self, 'update_status'):
            self.update_status = {"LoL": {}, "SC2": {}}
        self.update_status[game][account_id] = {
            "status": status,
            "has_changes": has_changes
        }

        # 2. Progress Bar Logic (Separate for each game)
        pb_attr = f"{game.lower()}_progress_bar"
        if not hasattr(self, pb_attr) or not getattr(self, pb_attr).winfo_exists():
            pb = ctk.CTkProgressBar(self.sidebar_bottom, width=200)
            setattr(self, pb_attr, pb)
        else:
            pb = getattr(self, pb_attr)

        if self.current_game == game:
            if not pb.winfo_ismapped() and current < total:
                pb.pack(pady=(0, 10))
            if total > 0:
                pb.set(current / total)
            if current >= total and status == "DONE":
                pb.pack_forget()
        else:
            if pb.winfo_ismapped():
                pb.pack_forget()

        # 3. Update Row Visuals
        if self.current_game == game:
            row_widgets = getattr(self, 'lol_row_widgets', {}) if game == "LoL" else getattr(self, 'sc2_row_widgets', {})
            
            if account_id in row_widgets:
                widgets = row_widgets[account_id]
                name_lbl = widgets.get('name_lbl')
                card = widgets.get('card')
                display_name = widgets.get('display_name', account_id)
                if not name_lbl or not card: return
                if not card.winfo_exists() or not name_lbl.winfo_exists(): return
                
                self._apply_row_style(card, name_lbl, display_name, status, has_changes)
                
                if status == "DONE" and has_changes:
                    # Refresh to show data
                    self.load_data()
                    if self.current_game == "SC2": self.show_sc2_view()
                    elif self.current_game == "LoL": self.show_lol_view()
                    
                    self.after(15000, lambda c=card, nl=name_lbl, orig=display_name, g=game: self._reset_row_highlight(c, nl, orig, g))

    def _apply_row_style(self, card, name_lbl, display_name, status, has_changes):
        if status == "SYNCING":
            name_lbl.configure(text_color="#d4a017")
        elif status == "DONE":
            if has_changes:
                card.configure(fg_color="#2c5a2c")
                name_lbl.configure(text=f"{display_name} ✨", text_color="#54B435")
            else:
                # Soft blueish color to differentiate from gray90 while still being readable in light mode
                name_lbl.configure(text_color=("#3a6ea5", "#a2c2e6"))
                card.configure(fg_color="transparent")

    def _reset_row_highlight(self, card, name_lbl, original_name, game):
        if hasattr(self, 'update_status') and game in self.update_status and original_name in self.update_status[game]:
            del self.update_status[game][original_name]
        try:
            if card.winfo_exists() and name_lbl.winfo_exists():
                card.configure(fg_color="transparent")
                name_lbl.configure(text=original_name, text_color=("gray10", "gray90"))
        except:
            pass

    def _on_update_success(self, game):
        self.updating[game] = False
        self.load_data()

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        key = "lol_updated" if game == "LoL" else "sc2_updated"
        self.settings[key] = now
        with open(SETTINGS_PATH, "w") as f:
            json.dump(self.settings, f)

        if self.current_game == game:
            self.update_timestamp_display()
            self.show_lol_view() if game == "LoL" else self.show_sc2_view()

            # ONLY show success message if the user is viewing this specific game
            import time
            elapsed = int(time.time() - self.update_start_times[game])
            mins, secs = divmod(elapsed, 60)
            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

            self.lbl_status.configure(text=f"{game} Update Success! ({time_str})", text_color="green")
            self.after(8000, self.clear_status)

        self.update_sidebar_state()

    def _on_update_failure(self, game):
        self.updating[game] = False
        self.update_sidebar_state()

        # ONLY show failure message if the user is viewing this specific game
        if self.current_game == game:
            self.lbl_status.configure(text=f"{game} Update Failed", text_color="red")
            self.after(4000, self.clear_status)

if __name__ == "__main__":
    app = AccountManagerApp()
    app.mainloop()