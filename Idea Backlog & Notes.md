## UI & General Account Management
- Account Disambiguation: Add a light grey email address below the account name to visually differentiate SC2 accounts that share the exact same display name.
- Make Accounts for both Games clickable (allows for a new layer of features, delete options, external links, plots, ....). The popup can be empty at first
- Rapid Deletion: Implement a dedicated delete button or symbol for each account to streamline the removal of test accounts from the UI.
- External Integrations: Provide quick links to external statistical webpages such as op.gg, deeplol, and u.gg directly from the account profiles.
- Past Rank UI Showcase: When a new season starts, display past ranks using a lighter color scheme instead of an "unranked" status, sorted logically between active ranks, previously known ranks and a true unranked status.

## Advanced Analytics & Visualization
- Streamlit Data Explorer: Build a Streamlit application hosted at the project root to visually explore available datasets. This is important since this will trigger new feature ideas, serves as validation, gives room for improvements etc.

## StarCraft II (SC2) Intelligence
- Live Dashboard & Opponent Unmasking: Detect when the user is in-game to extract the current opponent's alias via the local port 6119 API. Query the SC2 Pulse API to reveal barcode identities and instantly gather the opponent's win rates and recent match statistics.
- API Bug Correction: Develop client-side logic to automatically detect true MMR ranges and correct the Blizzard API bug that erroneously returns the "Master" league for Gold, Platinum, or Diamond ranked accounts.
- Placement Match Tracking: Track remaining placement matches (if possible), specifically calculating the difference between the 10 distinct daily wins required for brand new accounts versus the standard 5 placement matches per race for returning accounts. If not possible, then we can simply assume that if an account is unranked and has < 10 career games this notes down the progress from an NEW account to an UNRANKED Account (A newly create accounts need 10 wins across 10 days to allow for ranked play, then another 5 ranked matches until placed)
- Local File Guardian: Automatically detect when a user logs into a new SC2 account locally (new, untracked Folder) for new Servers this should automatically be detected when syncing. When there are untracked folders, prompt the user to link it in the app. Also note the user if accounts in the database have no longer a local profile folder.
- Smart Replay Management: A new use-case with various amounts of features. Sc2-Replay-Renamer (e.g. https://github.com/BurnySc2/SC2-Replay-Renamer, https://github.com/dericktseng/sc2-replay-renamer (potentially both outdated), Build Order Extractor, Other Analysis tools, ...
- Grandmaster Logic: Fetch Grandmaster Bar of Entry --> Each account can be flagged as potential Grandmaster. If MMR Bar is reached, we need to fullfill all requirements: "Besides maintaining a high enough MMR, Grandmaster players need to play at least 30 games every 3 weeks (or since season start if new season) to retain their spot." This also can include a decay warning if currently GM and in danger of dropping out.


## League of Legends (LoL) Analytics
- Role/Champion-Specific Benchmarking: Generate Stats & compare the user's KDA, CS, Gold metrics, etc. against the average statistics for their current rank to highlight specific areas for improvement.
- Decay Shield Live Tracker: Implement a visual "battery" or progress bar indicating exactly how many banked days are left before LP decay triggers.
- Teammate & Champion Synergies: Calculate and identify which specific teammates or champions yield the highest win rates.
- Timeline Visualization: Fetch match timelines to draw comprehensive "Gold Lead over Time" graphs.
- Item Build Paths: Visualize exactly which items were purchased and in what chronological sequence.
- Item Build Tool: Can we actually have access to the In-Game Item-Sets? We could create a tool that immediately shares one set across all linked accounts (makes accessible for all at once)
- Link 



## Backlog (unfinished idea dump)
- Did we refactor?
- Did we maximize all data crawling (All endpoints, max amount of data, time, additional accounts?)
- Did we versionize data accordingly to prepare for new season/resets & generally the usage of the local data in the future
- Beautify current UI (color schema, rendering, highlighting, ...) Make everything more beautiful & cleaner!
- Did we fix Sc2 update time taken?  If maximizing API requests and its still too slow --> more effciency in silent updateing vs UI updating
- Integrate & Brainstorm about all endpoints --> Local App Data Integration.md
- Can we integrate sc2 ladder rank versioning? Master 3,2,1 instead of Master, ...
- Brainstorm features by researching Reddit, GitHub for other ideas and implementations
- Do we load all static data separately (more rarely) then all dynamic data? --> Maybe we can also fetch item icons, champion icons, etc.
- Prepare assets for Sc2 (Race Logos, ...) for a more beautiful interface

- Brainstorm Analysis & Visualization Possibilities for both games

## Feature Ideas for LoL
*   **Role-Specific Benchmarking:** Compare your KDA/CS/Gold against average stats for your current rank to see where you are lacking.
*   **Decay Shield Live Tracker:** A visual "battery" or progress bar showing how many banked days you have left.
*   **Synergies:** Identify which teammates and/or champions you win with most often.
*   **Quick Links:** Quick Links to External Stat webpages such as op.gg, deeplol, u.gg, ...
*   **Match History:**
*   **Rank/LP History:** Visualize via Graph
*   **Aggregations:** Aggregated Stats across all Accounts
*   **Top Champs:** Best Champs + Stats

## Feature Ideas for SC2
*   **Local File Guardian:** Automatically detect if you log into a new account and prompt to link it in the app. (Also Check/Cleanse account that have no profile folder anymore)
*   **Replay Renamer** Rename Replays smartly
*   **Live Dashboard**: Get the current opponent if ingame --> INGAME DETECTION , if barcode/hidden/in general lookup on pulse if we can reveal it, gather stats like winrate, recent matches etc. for opponent.
*   **Placement Matches**: Can we see how many placements (per Server-Race-Combination) are still left? (differentiation between 10 wins on 10 different days for brandnew accounts and 0/5 placement matches per race if account is new in ranked or long time not played)


---