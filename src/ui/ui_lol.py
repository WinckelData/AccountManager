import customtkinter as ctk

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

    # Formula: (Tier * 10000) + (Division * 100) + LP
    # Example: Gold II, 50 LP -> (3 * 10000) + (2 * 100) + 50 = 30250
    return (tier_val * 10000) + (div_val * 100) + lp_val

def render_lol_view(container, data, copy_callback, add_callback, logo_img=None, row_widgets=None):
    """Renders the LoL account dashboard with header and add button using DTOs."""
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
        data.sort(key=lambda x: x.account_name.lower(), reverse=not sort_asc)
    elif sort_col == "Solo/Duo Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "solo"), reverse=not sort_asc)
    elif sort_col == "Flex Rank":
        data.sort(key=lambda x: get_rank_sort_key(x, "flex"), reverse=not sort_asc)

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

    tier_colors = {
        "IRON": "gray50", "BRONZE": "#cd7f32", "SILVER": "gray75",
        "GOLD": "#ffd700", "PLATINUM": "#00ced1", "EMERALD": "#50c878",
        "DIAMOND": "#b9f2ff", "MASTER": "#ff00ff", "GRANDMASTER": "#ff4500",
        "CHALLENGER": "#ffdf00", "UNRANKED": "gray40"
    }

    # --- Account Cards (Table Rows) ---
    for acc in data:
        name = acc.account_name
        
        # If we already created this row, just pack it again (which moves it to the bottom, applying the new sort order instantly!)
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
        
        def build_rank_cell(rank_data, col, dict_key):
            cell = ctk.CTkFrame(card, fg_color="transparent")
            cell.grid(row=0, column=col, padx=15, pady=10, sticky="w")
            row_widgets[name][dict_key] = cell
            
            if rank_data and rank_data.tier != "UNRANKED":
                t_color = tier_colors.get(rank_data.tier.upper(), "white")
                
                tier_str = f"{rank_data.tier.capitalize()} {rank_data.rank}"
                ctk.CTkLabel(cell, text=tier_str, text_color=t_color, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 8))
                
                ctk.CTkLabel(cell, text=f"{rank_data.lp} LP", text_color="gray50").pack(side="left", padx=(0, 8))
                
                winrate = 0
                total_games = rank_data.wins + rank_data.losses
                if total_games > 0:
                    winrate = int((rank_data.wins / total_games) * 100)
                
                wr_color = "gray50"
                if winrate >= 60: wr_color = "#ff4500"
                elif winrate >= 55: wr_color = "#32cd32"
                elif winrate < 48: wr_color = "#ff6347"
                
                ctk.CTkLabel(cell, text=f"{winrate}%", text_color=wr_color).pack(side="left")
            else:
                ctk.CTkLabel(cell, text="Unranked", text_color="gray50").pack(side="left")

        build_rank_cell(acc.solo_duo_rank, 1, 'solo_frame')
        build_rank_cell(acc.flex_rank, 2, 'flex_frame')

        copy_btn = ctk.CTkButton(card, text="📋 Copy Login", width=110, command=lambda ln=acc.login_name: copy_callback(ln))
        copy_btn.grid(row=0, column=3, padx=15, pady=10, sticky="e")
