import time
import customtkinter as ctk

from src.lol.live import QUEUE_NAMES


def get_rank_sort_key(acc, rank_type):
    """Parses a RankDTO into a comparable absolute integer score."""
    rank_data = acc.solo_duo_rank if rank_type == "solo" else acc.flex_rank

    if not rank_data or rank_data.tier == "UNRANKED":
        return -1

    tier_str = rank_data.tier.capitalize()
    div_str = rank_data.rank
    lp_val = rank_data.lp

    tiers = {"Iron": 0, "Bronze": 1, "Silver": 2, "Gold": 3, "Platinum": 4, "Emerald": 5, "Diamond": 6, "Master": 7,
             "Grandmaster": 8, "Challenger": 9}
    divisions = {"IV": 0, "III": 1, "II": 2, "I": 3}

    tier_val = tiers.get(tier_str, -1)
    if tier_val == -1:
        return -1

    div_val = divisions.get(div_str, 0)
    return (tier_val * 10000) + (div_val * 100) + lp_val


def _format_last_played(epoch_ms):
    """Convert epoch ms to a human-readable 'X days ago' string."""
    if epoch_ms is None or epoch_ms <= 0:
        return "Never"
    elapsed = time.time() - (epoch_ms / 1000)
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m ago"
    elif elapsed < 86400:
        return f"{int(elapsed // 3600)}h ago"
    else:
        days = int(elapsed // 86400)
        return f"{days}d ago"


def _confirm_delete(parent, name, on_confirm):
    """Show a modal confirmation dialog. Calls on_confirm() if user clicks Delete."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Confirm Delete")
    dialog.geometry("340x150")
    dialog.resizable(False, False)
    dialog.grab_set()

    ctk.CTkLabel(dialog, text=f"Delete '{name}'?",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(20, 6))
    ctk.CTkLabel(dialog, text="This cannot be undone.",
                 text_color="gray50", font=ctk.CTkFont(size=12)).pack()

    btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_row.pack(pady=16)

    def do_delete():
        dialog.destroy()
        on_confirm()

    ctk.CTkButton(btn_row, text="Delete", fg_color="#8b1a1a", hover_color="#b22222",
                  width=100, command=do_delete).pack(side="left", padx=8)
    ctk.CTkButton(btn_row, text="Cancel", fg_color="gray30", hover_color="gray40",
                  width=100, command=dialog.destroy).pack(side="left", padx=8)


def render_lol_view(container, data, copy_callback, add_callback, logo_img=None, row_widgets=None,
                    delete_callback=None, live_tracking_enabled=False, live_tracking_toggle_cb=None):
    """Renders the LoL account dashboard with header and add button using DTOs."""
    if row_widgets is None:
        row_widgets = {}

    # Persist live tracking state across internal re-renders
    if live_tracking_toggle_cb is not None:
        container._live_tracking_enabled = live_tracking_enabled
        container._live_tracking_toggle_cb = live_tracking_toggle_cb
    _live_enabled = getattr(container, "_live_tracking_enabled", False)
    _live_cb = getattr(container, "_live_tracking_toggle_cb", None)

    sort_col = getattr(container, "sort_col", "Solo/Duo Rank")
    sort_asc = getattr(container, "sort_asc", False)

    def set_sort(col):
        if getattr(container, "sort_col", "Solo/Duo Rank") == col:
            container.sort_asc = not getattr(container, "sort_asc", False)
        else:
            container.sort_col = col
            container.sort_asc = False
        render_lol_view(container, data, copy_callback, add_callback, logo_img, row_widgets, delete_callback)

    if sort_col == "Riot ID":
        data.sort(key=lambda x: x.account_name.lower(), reverse=not sort_asc)
    elif sort_col == "Solo/Duo Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "solo"), reverse=not sort_asc)
    elif sort_col == "Flex Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "flex"), reverse=not sort_asc)

    # Pin live and post-game accounts to top (only when live tracking is active)
    if _live_enabled:
        data.sort(key=lambda x: 0 if (x.is_in_game or x.last_game_result is not None) else 1)

    # Destroy non-row widgets; pack_forget row widgets
    for widget in container.winfo_children():
        is_row = any(widget == rw.get('card') for rw in row_widgets.values())
        if not is_row:
            widget.destroy()
        else:
            widget.pack_forget()

    # --- Header ---
    header_frame = ctk.CTkFrame(container, fg_color="transparent")
    header_frame.pack(fill="x", pady=(0, 20))

    if logo_img:
        ctk.CTkLabel(header_frame, text="", image=logo_img).pack(side="left", padx=(0, 15))

    ctk.CTkLabel(header_frame, text="League of Legends Accounts",
                 font=ctk.CTkFont(size=32, weight="bold")).pack(side="left")

    if _live_cb is not None:
        live_var = ctk.BooleanVar(value=_live_enabled)
        def _on_live_toggle():
            container._live_tracking_enabled = live_var.get()
            _live_cb(live_var.get())
        ctk.CTkCheckBox(header_frame, text="Live Tracking", variable=live_var,
                        command=_on_live_toggle, font=ctk.CTkFont(size=12)).pack(side="right", padx=10)

    ctk.CTkButton(header_frame, text="+ Add Account", fg_color="#1f538d", hover_color="#14375e",
                  height=35, command=add_callback).pack(side="right", padx=10)

    # --- Table Headers (4 columns) ---
    table_header = ctk.CTkFrame(container, fg_color="transparent")
    table_header.pack(fill="x", pady=(0, 5), padx=5)
    table_header.grid_columnconfigure(0, weight=2, uniform="col")
    table_header.grid_columnconfigure(1, weight=2, uniform="col")
    table_header.grid_columnconfigure(2, weight=2, uniform="col")
    table_header.grid_columnconfigure(3, weight=0, minsize=140)

    def create_header_btn(parent, text, col_name, col_idx):
        display_text = text
        if sort_col == col_name:
            display_text += " ▲" if sort_asc else " ▼"
        btn = ctk.CTkButton(parent, text=display_text, font=ctk.CTkFont(weight="bold"),
                            text_color=("gray30", "gray80"), fg_color="transparent",
                            hover_color=("gray85", "gray25"), anchor="w",
                            command=lambda c=col_name: set_sort(c))
        btn.grid(row=0, column=col_idx, sticky="w", padx=15)

    create_header_btn(table_header, "Riot ID", "Riot ID", 0)
    create_header_btn(table_header, "Solo/Duo Rank", "Solo/Duo Rank", 1)
    create_header_btn(table_header, "Flex Rank", "Flex Rank", 2)
    ctk.CTkLabel(table_header, text="", width=110).grid(row=0, column=3, padx=15)

    tier_colors = {
        "IRON": "gray50", "BRONZE": "#cd7f32", "SILVER": "gray75",
        "GOLD": "#ffd700", "PLATINUM": "#00ced1", "EMERALD": "#50c878",
        "DIAMOND": "#b9f2ff", "MASTER": "#ff00ff", "GRANDMASTER": "#ff4500",
        "CHALLENGER": "#ffdf00", "UNRANKED": "gray40",
    }

    # --- Account Cards ---
    for acc in data:
        name = acc.account_name

        if name in row_widgets:
            old_card = row_widgets[name].get('card')
            if old_card and old_card.winfo_exists():
                if str(old_card.winfo_parent()) == str(container):
                    old_card.pack(fill="x", pady=2, padx=5)
                    continue
                else:
                    old_card.destroy()

        card = ctk.CTkFrame(container)
        card.pack(fill="x", pady=2, padx=5)
        card.grid_columnconfigure(0, weight=2, uniform="col")
        card.grid_columnconfigure(1, weight=2, uniform="col")
        card.grid_columnconfigure(2, weight=2, uniform="col")
        card.grid_columnconfigure(3, weight=0, minsize=140)

        row_widgets[name] = {'card': card, 'display_name': name, 'name_lbl': None}

        # --- Column 0: Name, Level, Last Played, Masteries ---
        name_cell = ctk.CTkFrame(card, fg_color="transparent")
        name_cell.grid(row=0, column=0, padx=15, pady=(8, 4), sticky="w")

        name_row = ctk.CTkFrame(name_cell, fg_color="transparent")
        name_row.pack(anchor="w")

        name_lbl = ctk.CTkLabel(name_row, text=name,
                     font=ctk.CTkFont(size=14, weight="bold"))
        name_lbl.pack(side="left")
        row_widgets[name]['name_lbl'] = name_lbl

        if acc.is_in_game:
            queue_name = QUEUE_NAMES.get(acc.current_game_queue_id, "Custom Game")
            ctk.CTkLabel(name_row, text=f" \U0001f534 LIVE \u2014 {queue_name}",
                         text_color="#ff4500",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(6, 0))
        elif acc.last_game_result is not None:
            # Post-game badge (ranked only)
            if acc.last_game_result == "Victory":
                badge_icon = "\u2705"
                badge_color = "#32cd32"
            else:
                badge_icon = "\u274c"
                badge_color = "#ff6347"
            badge_text = f" {badge_icon} {acc.last_game_result}"
            if acc.last_game_lp_change is not None:
                sign = "+" if acc.last_game_lp_change >= 0 else ""
                badge_text += f" {sign}{acc.last_game_lp_change} LP"
            ctk.CTkLabel(name_row, text=badge_text,
                         text_color=badge_color,
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(6, 0))

        sub_row = ctk.CTkFrame(name_cell, fg_color="transparent")
        sub_row.pack(anchor="w")
        ctk.CTkLabel(sub_row, text=f"Lv.{acc.summoner_level}",
                     text_color="gray50", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))

        lp_text = _format_last_played(acc.last_played)
        ctk.CTkLabel(sub_row, text=f"|  {lp_text}",
                     text_color="gray50", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))

        if acc.games_this_week > 0:
            ctk.CTkLabel(sub_row, text=f"|  {acc.games_this_week} this week",
                         text_color="gray50", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))

        # Live game timer
        if acc.is_in_game and acc.current_game_start:
            timer_lbl = ctk.CTkLabel(sub_row, text="",
                                     text_color="gray50", font=ctk.CTkFont(size=11))
            timer_lbl.pack(side="left", padx=(0, 6))
            elapsed_s = int((time.time() * 1000 - acc.current_game_start) / 1000)
            mins, secs = divmod(max(0, elapsed_s), 60)
            timer_lbl.configure(text=f"|  {mins}:{secs:02d}")
            row_widgets[name]['timer_lbl'] = timer_lbl

# --- Columns 1 & 2: Rank cells ---
        def build_rank_cell(rank_data, col):
            cell = ctk.CTkFrame(card, fg_color="transparent")
            cell.grid(row=0, column=col, padx=15, pady=10, sticky="w")

            if rank_data and rank_data.tier != "UNRANKED":
                t_color = tier_colors.get(rank_data.tier.upper(), "white")

                top = ctk.CTkFrame(cell, fg_color="transparent")
                top.pack(anchor="w")
                ctk.CTkLabel(top, text=f"{rank_data.tier.capitalize()} {rank_data.rank}",
                             text_color=t_color, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 6))
                ctk.CTkLabel(top, text=f"{rank_data.lp} LP",
                             text_color="gray50").pack(side="left")

                # LP delta
                if rank_data.lp_delta != 0:
                    delta_color = "#32cd32" if rank_data.lp_delta > 0 else "#ff6347"
                    delta_sign = "+" if rank_data.lp_delta > 0 else ""
                    ctk.CTkLabel(top, text=f"  {delta_sign}{rank_data.lp_delta}",
                                 text_color=delta_color,
                                 font=ctk.CTkFont(size=11)).pack(side="left")

                bot = ctk.CTkFrame(cell, fg_color="transparent")
                bot.pack(anchor="w")
                total = rank_data.wins + rank_data.losses
                wr = int((rank_data.wins / total) * 100) if total > 0 else 0
                wr_color = "#ff4500" if wr >= 60 else "#32cd32" if wr >= 55 else "#ff6347" if wr < 48 else "gray50"
                ctk.CTkLabel(bot, text=f"W{rank_data.wins} L{rank_data.losses}  {wr}%",
                             text_color=wr_color,
                             font=ctk.CTkFont(size=11)).pack(side="left")
            else:
                ctk.CTkLabel(cell, text="Unranked", text_color="gray50").pack(side="left")

        build_rank_cell(acc.solo_duo_rank, 1)
        build_rank_cell(acc.flex_rank, 2)

        # --- Column 3: Copy + Delete buttons ---
        btn_cell = ctk.CTkFrame(card, fg_color="transparent")
        btn_cell.grid(row=0, column=3, padx=15, pady=10, sticky="e")

        ctk.CTkButton(btn_cell, text="📋 Copy Login", width=110,
                      command=lambda ln=acc.login_name: copy_callback(ln)
                      ).pack(side="left", padx=(0, 6))

        if delete_callback:
            ctk.CTkButton(btn_cell, text="🗑", width=36, fg_color="gray25", hover_color="#8b1a1a",
                          command=lambda a=acc: _confirm_delete(
                              container, a.account_name, lambda: delete_callback(a.account_id)
                          )).pack(side="left")
