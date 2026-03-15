import customtkinter as ctk
import threading
import os
import re
from src.services.data_service import add_lol_account, add_sc2_account

def get_sc2_account_folders():
    """Scans the SC2 Documents directory for root account folders."""
    base_dir = os.path.expanduser('~/Documents/StarCraft II/Accounts')
    folders = []
    if os.path.exists(base_dir):
        for item in os.listdir(base_dir):
            full_path = os.path.join(base_dir, item)
            # Check if it's a directory and looks like an account ID (numbers)
            if os.path.isdir(full_path) and item.isdigit():
                # Count profiles inside
                profile_count = 0
                for root, dirs, files in os.walk(full_path):
                    if re.search(r'\d-S2-\d-\d+', root):
                        profile_count += 1
                if profile_count > 0:
                    folders.append((item, profile_count))
    return folders

def open_add_modal(app):
    """Opens a unified modal for adding accounts with API verification."""
    modal = ctk.CTkToplevel(app)
    modal.title(f"Add {app.current_game} Account")
    modal.geometry("450x450")
    modal.transient(app)
    modal.grab_set()

    # Center the modal
    modal.update_idletasks()
    x = app.winfo_x() + (app.winfo_width() // 2) - (modal.winfo_width() // 2)
    y = app.winfo_y() + (app.winfo_height() // 2) - (modal.winfo_height() // 2)
    modal.geometry(f"+{x}+{y}")

    entries = {}

    if app.current_game == "LoL":
        ctk.CTkLabel(modal, text="Login Name (For Clipboard):", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 0), padx=20, anchor="w")
        entries['login'] = ctk.CTkEntry(modal, width=400, placeholder_text="e.g. superSlayer99")
        entries['login'].pack(pady=(5, 15), padx=20)

        ctk.CTkLabel(modal, text="Riot ID (In-Game Name):", font=ctk.CTkFont(weight="bold")).pack(pady=(0, 0), padx=20, anchor="w")
        entries['game_name'] = ctk.CTkEntry(modal, width=400, placeholder_text="e.g. Winckel")
        entries['game_name'].pack(pady=(5, 15), padx=20)

        ctk.CTkLabel(modal, text="Tagline (e.g. EUW):", font=ctk.CTkFont(weight="bold")).pack(pady=(0, 0), padx=20, anchor="w")
        entries['tagline'] = ctk.CTkEntry(modal, width=400, placeholder_text="e.g. EUW")
        entries['tagline'].insert(0, "EUW")
        entries['tagline'].pack(pady=(5, 15), padx=20)
    else:
        # SC2 UI Overhaul: Folder Picker instead of messy dropdowns
        from tkinter import filedialog
        
        ctk.CTkLabel(modal, text="Local SC2 Account Folder:", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 0), padx=20, anchor="w")
        
        folder_frame = ctk.CTkFrame(modal, fg_color="transparent")
        folder_frame.pack(fill="x", padx=20, pady=(5, 15))
        
        entries['folder'] = ctk.CTkEntry(folder_frame, placeholder_text="Browse to select...", state="readonly")
        entries['folder'].pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        def pick_folder():
            base = os.path.expanduser('~/Documents/StarCraft II/Accounts')
            # If path doesn't exist, default to ~
            initial_dir = base if os.path.exists(base) else os.path.expanduser('~')
            folder_path = filedialog.askdirectory(initialdir=initial_dir, title="Select Battle.net Account Folder")
            if folder_path:
                folder_id = os.path.basename(folder_path)
                entries['folder'].configure(state="normal")
                entries['folder'].delete(0, 'end')
                entries['folder'].insert(0, folder_id)
                entries['folder'].configure(state="readonly")
                
        btn_browse = ctk.CTkButton(folder_frame, text="Browse", width=80, command=pick_folder)
        btn_browse.pack(side="right")

        ctk.CTkLabel(modal, text="Account Email (To link to this folder):", font=ctk.CTkFont(weight="bold")).pack(pady=(0, 0), padx=20, anchor="w")
        entries['email'] = ctk.CTkEntry(modal, width=400, placeholder_text="e.g. player@gmail.com")
        entries['email'].pack(pady=(5, 15), padx=20)
        
        # Removed Account Alias per request; API will dictate name.

    # --- Error Label ---
    error_lbl = ctk.CTkLabel(modal, text="", text_color="red")
    error_lbl.pack(pady=5)

    # --- Actions ---
    def start_verification():
        error_lbl.configure(text="Processing...", text_color="orange")
        verify_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")

        # Start thread to avoid freezing modal
        threading.Thread(target=run_verification, args=(entries,), daemon=True).start()

    def run_verification(data_entries):
        if app.current_game == "LoL":
            login = data_entries['login'].get().strip()
            name = data_entries['game_name'].get().strip()
            tag = data_entries['tagline'].get().strip()

            if not name or not tag:
                app.after(0, finish_verification, "Game Name and Tagline are required.")
                return

            success, error = add_lol_account(login, name, tag)
            if not success:
                app.after(0, finish_verification, error)
                return

            app.after(0, finish_success)

        else: # SC2
            folder_selection = data_entries['folder'].get()
            if not folder_selection or folder_selection == "No local SC2 accounts found.":
                app.after(0, finish_verification, "No folder selected.")
                return

            folder_id = folder_selection.split(" ")[0]
            email = data_entries['email'].get().strip()

            if not email:
                app.after(0, finish_verification, "Email is required.")
                return

            success, error = add_sc2_account(folder_id, email)
            if not success:
                app.after(0, finish_verification, error)
                return

            app.after(0, finish_success)


    def finish_verification(error_msg):
        error_lbl.configure(text=error_msg, text_color="red")
        verify_btn.configure(state="normal")
        cancel_btn.configure(state="normal")

    def finish_success():
        app.load_data()
        app.show_lol_view() if app.current_game == "LoL" else app.show_sc2_view()
        modal.destroy()

    btn_frame = ctk.CTkFrame(modal, fg_color="transparent")
    btn_frame.pack(fill="x", padx=20, pady=10, side="bottom")

    cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", fg_color="gray", hover_color="#555555", command=modal.destroy)
    cancel_btn.pack(side="left", expand=True, padx=5)

    verify_btn = ctk.CTkButton(btn_frame, text="Verify & Save", fg_color="#2B7A0B", hover_color="#54B435", command=start_verification)
    verify_btn.pack(side="right", expand=True, padx=5)