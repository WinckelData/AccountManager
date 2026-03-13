import customtkinter as ctk


def get_rank_sort_key(acc, rank_type):
    """Parses a rank string or dictionary into a comparable absolute integer score."""
    rank_data = acc.get(rank_type, 'Unranked')

    if isinstance(rank_data, dict):
        tier_str = rank_data.get('tier', 'Unknown').capitalize()
        div_str = rank_data.get('rank', '')
        lp_val = rank_data.get('leaguePoints', 0)
    else:
        # Fallback if the JSON hasn't been updated yet and is still a string
        if not rank_data or rank_data == 'Unranked':
            return -1
        parts = rank_data.split(" ")
        tier_str = parts[0].capitalize() if len(parts) > 0 else "Unknown"
        div_str = parts[1] if len(parts) > 1 else ""
        lp_val = 0
        if len(parts) > 2:
            try:
                lp_val = int(parts[2].replace("(", ""))
            except ValueError:
                pass

    tiers = {"Iron": 0, "Bronze": 1, "Silver": 2, "Gold": 3, "Platinum": 4, "Emerald": 5, "Diamond": 6, "Master": 7,
             "Grandmaster": 8, "Challenger": 9}
    divisions = {"IV": 0, "III": 1, "II": 2, "I": 3}

    tier_val = tiers.get(tier_str, -1)
    if tier_val == -1:
        return -1

    div_val = divisions.get(div_str, 0)

    # Formula: (Tier * 10000) + (Division * 100) + LP
    # Example: Gold II, 50 LP -> (3 * 10000) + (2 * 100) + 50 = 30250
    return (tier_val * 10000) + (div_val * 100) + lp_val

def render_lol_view(container, data, copy_callback, add_callback, logo_img=None, row_widgets=None):
    """Renders the LoL account dashboard with header and add button."""
    if row_widgets is None:
        row_widgets = {}
    
    # State management for sorting attached to the container
    sort_col = getattr(container, "sort_col", "Solo/Duo Rank")
    sort_asc = getattr(container, "sort_asc", False)

    def set_sort(col):
        if getattr(container, "sort_col", "Solo/Duo Rank") == col:
            container.sort_asc = not getattr(container, "sort_asc", False)
        else:
            container.sort_col = col
            container.sort_asc = False
        # Re-render UI
        render_lol_view(container, data, copy_callback, add_callback, logo_img, row_widgets)

    # Apply sorting dynamically to the data before rendering
    if sort_col == "Riot ID":
        data.sort(key=lambda x: x.get("account_name", "").lower(), reverse=not sort_asc)
    elif sort_col == "Solo/Duo Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "api_solo_duo"), reverse=not sort_asc)
    elif sort_col == "Flex Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "api_flex"), reverse=not sort_asc)

    # Only destroy headers, keep the cached rows
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
    header_frame.pack(fill="x", pady=(0, 20))

    if logo_img:
        logo_label = ctk.CTkLabel(header_frame, text="", image=logo_img)
        logo_label.pack(side="left", padx=(0, 15))

    title = ctk.CTkLabel(header_frame, text="League of Legends Accounts", font=ctk.CTkFont(size=32, weight="bold"))
    title.pack(side="left")

    # --- Add Account Button (Header) ---
    add_btn = ctk.CTkButton(header_frame, text="+ Add Account", fg_color="#1f538d", hover_color="#14375e",
                            height=35, command=add_callback)
    add_btn.pack(side="right", padx=10)

    # --- Table Headers ---
    table_header = ctk.CTkFrame(container, fg_color="transparent")
    table_header.pack(fill="x", pady=(0, 5), padx=5)
    table_header.grid_columnconfigure(0, weight=1, uniform="col")
    table_header.grid_columnconfigure(1, weight=1, uniform="col")
    table_header.grid_columnconfigure(2, weight=1, uniform="col")
    table_header.grid_columnconfigure(3, weight=0, minsize=140)

    # Helper for creating sortable header buttons
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

    create_header_btn(table_header, "Riot ID", "Riot ID", 0, 200)
    create_header_btn(table_header, "Solo/Duo Rank", "Solo/Duo Rank", 1, 180)
    create_header_btn(table_header, "Flex Rank", "Flex Rank", 2, 180)
    
    # Dummy label to enforce exact column width matching with the cards below
    ctk.CTkLabel(table_header, text="", width=110).grid(row=0, column=3, padx=15)

    # --- Account Cards (Table Rows) ---
    for acc in data:
        name = acc.get('account_name', 'Unknown')
        
        # If we already created this row, just pack it again (which moves it to the bottom, applying the new sort order instantly!)
        if name in row_widgets:
            old_card = row_widgets[name].get('card')
            if old_card and old_card.winfo_exists():
                if old_card.winfo_parent() == container.winfo_name():
                    old_card.pack(fill="x", pady=2, padx=5)
                    continue
                else:
                    old_card.destroy()
            
        card = ctk.CTkFrame(container)
        card.pack(fill="x", pady=2, padx=5)
        card.grid_columnconfigure(0, weight=1, uniform="col")
        card.grid_columnconfigure(1, weight=1, uniform="col")
        card.grid_columnconfigure(2, weight=1, uniform="col")
        card.grid_columnconfigure(3, weight=0, minsize=140)

        name_lbl = ctk.CTkLabel(card, text=name, font=ctk.CTkFont(size=14, weight="bold"), width=200, anchor="w")
        name_lbl.grid(row=0, column=0, padx=15, pady=10, sticky="w")
        
        # We will save references here so main.py can update them later
        row_widgets[name] = {
            'card': card,
            'name_lbl': name_lbl,
            'solo_frame': None,
            'flex_frame': None,
            'display_name': name
        }

        # --- Sub-frames for precise Rank and LP alignment (Left-Aligned Method) ---
        def create_rank_cell(parent, rank_data, col, dict_key):
            cell = ctk.CTkFrame(parent, fg_color="transparent")
            cell.grid(row=0, column=col, padx=15, pady=10, sticky="w")
            row_widgets[name][dict_key] = cell
            
            is_dict = isinstance(rank_data, dict)
            rank_string = f"{rank_data.get('tier', 'Unknown').title()} {rank_data.get('rank', '')} ({rank_data.get('leaguePoints', 0)} LP)" if is_dict else str(rank_data)
            
            # --- Row 1: Rank and LP ---
            r_frame = ctk.CTkFrame(cell, fg_color="transparent")
            r_frame.pack(anchor="w")
            
            if "(" in rank_string:
                rank_part, lp_part = rank_string.split(" (", 1)
                lp_part = "(" + lp_part
            else:
                rank_part = rank_string
                lp_part = ""

            rank_lbl = ctk.CTkLabel(r_frame, text=rank_part, width=100, anchor="w")
            rank_lbl.pack(side="left", padx=(0, 5))
            
            if lp_part:
                lp_lbl = ctk.CTkLabel(r_frame, text=lp_part, text_color="gray", width=60, anchor="w")
                lp_lbl.pack(side="left")
            else:
                ctk.CTkLabel(r_frame, text="", width=60).pack(side="left")
                
            # --- Decay Warning (Lookahead) ---
            decay_data = acc.get('decay_solo_duo') if col == 1 else None # Assuming we only really care about Solo/Duo decay for now
            if decay_data and is_dict:
                import time
                calc_time = decay_data.get("calculated_at", 0)
                bank = decay_data.get("bank", 0)
                
                elapsed_seconds = time.time() - calc_time
                elapsed_days = int(elapsed_seconds / 86400)
                current_bank = max(0, bank - elapsed_days)
                
                if current_bank <= 7:
                    color = "#cc3333" if current_bank <= 3 else "#d4a017"
                    decay_lbl = ctk.CTkLabel(r_frame, text=f"⚠️ {current_bank}d", text_color=color, font=ctk.CTkFont(size=11, weight="bold"))
                    decay_lbl.pack(side="left", padx=(5, 0))

            # --- Row 2: Winrate (Only if dictionary) ---
            if is_dict and "wins" in rank_data and "losses" in rank_data:
                w = rank_data["wins"]
                l = rank_data["losses"]
                total = w + l
                if total > 0:
                    wr = (w / total) * 100
                    
                    # Color coding
                    wr_color = "#54B435" if wr >= 53 else ("#d4a017" if wr >= 50 else "#cc3333")
                    
                    wr_frame = ctk.CTkFrame(cell, fg_color="transparent")
                    wr_frame.pack(anchor="w", pady=(2, 0))
                    
                    ctk.CTkLabel(wr_frame, text=f"{wr:.1f}% WR", text_color=wr_color, font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(0, 5))
                    ctk.CTkLabel(wr_frame, text=f"({w}W - {l}L)", text_color="gray60", font=ctk.CTkFont(size=11)).pack(side="left")

        create_rank_cell(card, acc.get('api_solo_duo', 'Unranked'), 1, 'solo_frame')
        create_rank_cell(card, acc.get('api_flex', 'Unranked'), 2, 'flex_frame')

        login_name = acc.get('login_name', '')
        copy_btn = ctk.CTkButton(card, text="📋 Copy Login", width=110, command=lambda ln=login_name: copy_callback(ln))
        copy_btn.grid(row=0, column=3, padx=15, pady=10, sticky="e")