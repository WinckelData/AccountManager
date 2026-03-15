import time
import customtkinter as ctk

def get_sc2_stats(acc, target_region, race):
    """
    Extracts the MMR and display string for a specific region and race from an SC2AccountDTO.
    Returns: (numeric_mmr, display_string, is_active)
    """
    race_key = race.lower()
    
    # acc is now an SC2AccountDTO, profiles is a List[SC2ProfileDTO]
    prof = next((p for p in acc.profiles if p.region == target_region), None)
    if not prof:
        return (0, "Unranked", False)

    # Check active
    ranks = prof.ranks
    if race_key in ranks and ranks[race_key].league != "Unranked":
        mmr = ranks[race_key].mmr
        return (mmr, f"{mmr} MMR ({ranks[race_key].league})", True)
        
    # Check history (History is still a dict parsed from raw JSON)
    history = prof.history
    if history:
        def extract_season_num(season_str):
            try: return int(season_str.replace("Season ", ""))
            except ValueError: return 0
            
        sorted_seasons = sorted(history.keys(), key=extract_season_num, reverse=True)
        for s in sorted_seasons:
            if race_key in history[s] and history[s][race_key].get("league") != "Unranked":
                mmr = history[s][race_key]["mmr"]
                return (mmr, f"History ({s}): {mmr} MMR", False)
                
    return (0, "Unranked", False)


def render_sc2_view(container, data, copy_callback, add_callback, logo_img=None, row_widgets=None,
                    live_tracking_enabled=False, live_tracking_toggle_cb=None):
    """Renders the SC2 account dashboard using the Compact Grid layout with Sorting and Spoilers."""
    if row_widgets is None:
        row_widgets = {}

    # --- State Management ---
    if not hasattr(container, "selected_server"):
        container.selected_server = "EU"
    if not hasattr(container, "selected_races"):
        container.selected_races = {"Zerg": True, "Terran": False, "Protoss": False}
    # Persist live tracking state across internal re-renders
    if live_tracking_toggle_cb is not None:
        container._live_tracking_enabled = live_tracking_enabled
        container._live_tracking_toggle_cb = live_tracking_toggle_cb
    _live_enabled = getattr(container, "_live_tracking_enabled", False)
    _live_cb = getattr(container, "_live_tracking_toggle_cb", None)
        
    selected_server = container.selected_server
    selected_races = container.selected_races
    
    # Active races ordered
    race_order = ["Zerg", "Terran", "Protoss"]
    active_races = [r for r in race_order if selected_races.get(r, False)]
    
    # If no races selected, default back to Zerg to prevent empty UI
    if not active_races:
        active_races = ["Zerg"]
        selected_races["Zerg"] = True

    server_map = {"NA": 1, "EU": 2, "KR": 3}
    target_region = server_map.get(selected_server, 2)
    
    # Layout signature to detect if we need to rebuild rows
    current_layout = f"{selected_server}_{','.join(active_races)}"
    if getattr(container, "last_layout", "") != current_layout:
        for widget in container.winfo_children():
            widget.destroy()
        row_widgets.clear()
        container.last_layout = current_layout

    # Fallback default sort column based on active races
    default_sort = f"{active_races[0]} MMR ({selected_server})"
    sort_col = getattr(container, "sort_col", default_sort)
    # Ensure sort_col is valid for current layout, otherwise reset
    valid_sort_cols = ["Name"] + [f"{r} MMR ({selected_server})" for r in active_races]
    if sort_col not in valid_sort_cols:
        sort_col = default_sort
        container.sort_col = sort_col

    sort_asc = getattr(container, "sort_asc", False)

    def set_sort(col):
        if getattr(container, "sort_col", default_sort) == col:
            container.sort_asc = not getattr(container, "sort_asc", False)
        else:
            container.sort_col = col
            container.sort_asc = False
        render_sc2_view(container, data, copy_callback, add_callback, logo_img, row_widgets)
        
    def trigger_rerender():
        render_sc2_view(container, data, copy_callback, add_callback, logo_img, row_widgets)

    # --- Data Parsing & Enrichment ---
    enriched_data = []
    for i, acc in enumerate(data):
        name = acc.account_name
        account_id = f"{name}_{acc.account_folder_id or i}"
        
        item_data = {
            "acc": acc,
            "name": name,
            "account_id": account_id,
            "stats": {}
        }
        
        is_empty = True
        for race in active_races:
            mmr, string, active = get_sc2_stats(acc, target_region, race)
            item_data["stats"][race] = {
                "mmr": mmr,
                "str": string,
                "active": active
            }
            if mmr > 0:
                is_empty = False
                
        item_data["is_empty"] = is_empty
        enriched_data.append(item_data)

    # --- Sorting Logic ---
    if sort_col == "Name":
        enriched_data.sort(key=lambda x: x["name"].lower(), reverse=not sort_asc)
    else:
        # Extract race from sort_col like "Zerg MMR (EU)"
        sort_race = sort_col.split(" ")[0]
        enriched_data.sort(
            key=lambda x: (
                x["stats"].get(sort_race, {}).get("mmr", 0),
                x["name"].lower() if not sort_asc else x["name"].lower()[::-1]
            ),
            reverse=not sort_asc
        )

    # Pin live or post-game accounts to top (only when live tracking is active)
    if _live_enabled:
        def _pin_key(x):
            for p in x["acc"].profiles:
                if p.is_in_game:
                    return 0  # in-game: highest priority
                if p.last_game_result is not None:
                    return 0  # post-game result: keep pinned
            return 1
        enriched_data.sort(key=_pin_key)

    # Separate empty accounts after sorting
    active_data = [d for d in enriched_data if not d["is_empty"]]
    empty_data = [d for d in enriched_data if d["is_empty"]]
    
    if sort_col != "Name" or (sort_col == "Name" and sort_asc):
        empty_data.sort(key=lambda x: x["name"].lower())

    # Only destroy non-row widgets, pack_forget row widgets
    for widget in container.winfo_children():
        is_row = False
        for rw in row_widgets.values():
            if widget == rw.get('card'):
                is_row = True
                break
        if not is_row:
            widget.destroy()
        else:
            widget.pack_forget()

    # --- Header ---
    header_frame = ctk.CTkFrame(container, fg_color="transparent")
    header_frame.pack(fill="x", pady=(0, 10))

    if logo_img:
        logo_label = ctk.CTkLabel(header_frame, text="", image=logo_img)
        logo_label.pack(side="left", padx=(0, 15))

    title = ctk.CTkLabel(header_frame, text="StarCraft II Accounts", font=ctk.CTkFont(size=32, weight="bold"))
    title.pack(side="left")

    if _live_cb is not None:
        live_var = ctk.BooleanVar(value=_live_enabled)
        def _on_live_toggle():
            container._live_tracking_enabled = live_var.get()
            _live_cb(live_var.get())
        ctk.CTkCheckBox(header_frame, text="Live Tracking", variable=live_var,
                        command=_on_live_toggle, font=ctk.CTkFont(size=12)).pack(side="right", padx=10)

    add_btn = ctk.CTkButton(header_frame, text="+ Add Account", fg_color="#1f538d", hover_color="#14375e",
                            height=35, command=add_callback)
    add_btn.pack(side="right", padx=10)

    # --- Filters ---
    filter_frame = ctk.CTkFrame(container, fg_color="transparent")
    filter_frame.pack(fill="x", pady=(0, 20), padx=5)
    
    server_label = ctk.CTkLabel(filter_frame, text="Server:", font=ctk.CTkFont(weight="bold"))
    server_label.pack(side="left", padx=(10, 5))
    
    def on_server_change(val):
        container.selected_server = val
        trigger_rerender()
        
    server_dropdown = ctk.CTkOptionMenu(filter_frame, values=["EU", "NA", "KR"], command=on_server_change, width=80)
    server_dropdown.set(selected_server)
    server_dropdown.pack(side="left", padx=5)
    
    race_label = ctk.CTkLabel(filter_frame, text="Races:", font=ctk.CTkFont(weight="bold"))
    race_label.pack(side="left", padx=(30, 5))
    
    def toggle_race(r, val):
        container.selected_races[r] = val
        trigger_rerender()

    for r in race_order:
        var = ctk.BooleanVar(value=selected_races[r])
        chk = ctk.CTkCheckBox(filter_frame, text=r, variable=var, width=60,
                              command=lambda r_name=r, v=var: toggle_race(r_name, v.get()))
        chk.pack(side="left", padx=5)

    # --- Table Headers ---
    table_header = ctk.CTkFrame(container, fg_color="transparent")
    table_header.pack(fill="x", pady=(0, 5), padx=5)
    
    # Configure Columns dynamically
    num_data_cols = len(active_races)
    table_header.grid_columnconfigure(0, weight=1, uniform="col") # Name
    for c in range(1, num_data_cols + 1):
        table_header.grid_columnconfigure(c, weight=1, uniform="col") # Races
    table_header.grid_columnconfigure(num_data_cols + 1, weight=0, minsize=140) # Copy btn

    def create_header_btn(parent, text, col_name, col_idx, width):
        display_text = text
        if sort_col == col_name:
            arrow = " ▲" if sort_asc else " ▼"
            display_text += arrow
            
        btn = ctk.CTkButton(parent, text=display_text, font=ctk.CTkFont(weight="bold"),
                            text_color=("gray30", "gray80"), fg_color="transparent", 
                            hover_color=("gray85", "gray25"), width=width, anchor="w", 
                            command=lambda c=col_name: set_sort(c))
        btn.grid(row=0, column=col_idx, sticky="w", padx=15)

    create_header_btn(table_header, "Name", "Name", 0, 200)
    
    for idx, race in enumerate(active_races):
        col_name = f"{race} MMR ({selected_server})"
        create_header_btn(table_header, col_name, col_name, idx + 1, 180)
        
    ctk.CTkLabel(table_header, text="", width=110).grid(row=0, column=num_data_cols + 1, padx=15)

    def create_card(parent, item, is_muted=False):
        account_id = item["account_id"]
        
        if account_id in row_widgets:
            old_card = row_widgets[account_id]['card']
            if old_card.winfo_exists():
                if old_card.winfo_parent() == str(parent):
                    old_card.pack(fill="x", pady=2, padx=5)
                    return
                else:
                    old_card.destroy()
                
        card = ctk.CTkFrame(parent, fg_color="transparent")
        card.pack(fill="x", pady=2, padx=5)
        
        card.grid_columnconfigure(0, weight=1, uniform="col")
        for c in range(1, num_data_cols + 1):
            card.grid_columnconfigure(c, weight=1, uniform="col")
        card.grid_columnconfigure(num_data_cols + 1, weight=0, minsize=140)
        
        row_widgets[account_id] = {
            'card': card,
            'display_name': item["name"],
            'race_lbls': {}
        }

        base_text_color = "gray60" if is_muted else ("gray10", "gray90")

        # Check if any profile for this account is in-game or has post-game result
        acc_obj = item["acc"]
        in_game_profile = next((p for p in acc_obj.profiles if p.is_in_game), None)
        result_profile = next((p for p in acc_obj.profiles if p.last_game_result is not None), None)

        name_cell = ctk.CTkFrame(card, fg_color="transparent")
        name_cell.grid(row=0, column=0, padx=15, pady=(8, 4), sticky="w")

        name_row = ctk.CTkFrame(name_cell, fg_color="transparent")
        name_row.pack(anchor="w")

        name_lbl = ctk.CTkLabel(name_row, text=item["name"], font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=base_text_color)
        name_lbl.pack(side="left")
        row_widgets[account_id]['name_lbl'] = name_lbl

        if not is_muted:
            if in_game_profile:
                ctk.CTkLabel(name_row, text=" 🔴 LIVE",
                             text_color="#ff4500",
                             font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(6, 0))
            elif result_profile:
                result_map = {
                    "Victory": ("✅ Victory", "#2ea043"),
                    "Defeat": ("❌ Defeat", "#da3633"),
                    "Tie": ("➖ Tie", "#d4a017"),
                }
                badge_text, badge_color = result_map.get(
                    result_profile.last_game_result, (result_profile.last_game_result, "gray50")
                )
                ctk.CTkLabel(name_row, text=f" {badge_text}",
                             text_color=badge_color,
                             font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(6, 0))

        # Sub-row: opponent and game timer
        if not is_muted:
            show_profile = in_game_profile or result_profile
            if show_profile:
                sub_row = ctk.CTkFrame(name_cell, fg_color="transparent")
                sub_row.pack(anchor="w")

                # Opponent name: use live opponent if in-game, else post-game opponent
                opponent = None
                if in_game_profile:
                    opponent = in_game_profile.current_opponent
                elif result_profile:
                    opponent = result_profile.last_game_opponent
                if opponent:
                    ctk.CTkLabel(sub_row, text=f"vs {opponent}",
                                 text_color="gray50", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))

                # Timer (only while in-game)
                if in_game_profile and in_game_profile.current_game_start:
                    elapsed_s = int((time.time() * 1000 - in_game_profile.current_game_start) / 1000)
                    mins, secs = divmod(max(0, elapsed_s), 60)
                    timer_lbl = ctk.CTkLabel(sub_row, text=f"|  {mins}:{secs:02d}",
                                 text_color="gray50", font=ctk.CTkFont(size=11))
                    timer_lbl.pack(side="left")
                    row_widgets[account_id]['timer_lbl'] = timer_lbl

        for idx, race in enumerate(active_races):
            stats = item["stats"][race]
            r_color = ("gray10", "gray90") if stats["active"] else "gray50"
            if is_muted:
                r_color = "gray60"
                
            lbl = ctk.CTkLabel(card, text=stats["str"], text_color=r_color, width=180, anchor="w")
            lbl.grid(row=0, column=idx + 1, padx=15, pady=10, sticky="w")
            row_widgets[account_id]['race_lbls'][race] = lbl

        email = item["acc"].email
        
        if is_muted:
            copy_btn = ctk.CTkButton(card, text="📋 Copy Email", width=110, 
                                     fg_color="transparent", hover_color="gray25", 
                                     border_width=1, border_color="gray30",
                                     text_color="gray60",
                                     command=lambda e=email: copy_callback(e))
        else:
            copy_btn = ctk.CTkButton(card, text="📋 Copy Email", width=110, 
                                     command=lambda e=email: copy_callback(e))
            
        copy_btn.grid(row=0, column=num_data_cols + 1, padx=15, pady=10, sticky="e")

    # --- Render Active Accounts ---
    for item in active_data:
        create_card(container, item)

    # --- Render Empty Accounts (Spoiler) ---
    if empty_data:
        spoiler_state = getattr(container, "spoiler_open", False)
        
        def toggle_spoiler():
            container.spoiler_open = not getattr(container, "spoiler_open", False)
            render_sc2_view(container, data, copy_callback, add_callback, logo_img, row_widgets)
            
        arrow = "▲" if spoiler_state else "▼"
        spoiler_btn = ctk.CTkButton(container, text=f"{arrow} Unranked Accounts ({len(empty_data)})", 
                                    fg_color="transparent", hover_color=("gray85", "gray25"), 
                                    text_color="gray50", command=toggle_spoiler)
        spoiler_btn.pack(pady=(20, 10))
        
        if spoiler_state:
            spoiler_frame = ctk.CTkFrame(container, fg_color="transparent")
            spoiler_frame.pack(fill="x")
            for item in empty_data:
                create_card(spoiler_frame, item, is_muted=True)