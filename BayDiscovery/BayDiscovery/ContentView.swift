//
//  ContentView.swift
//  BayDiscovery
//
//  Created by Leonardo Flores Gonzalez on 6/19/26.
//

import Foundation
import SwiftUI
import SwiftData

struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \LocalDiscoveryItem.dateDiscovered, order: .reverse) private var discoveries: [LocalDiscoveryItem]
    
    // Tab state
    @State private var selectedTab = 0
    
    // Sync & Interaction States
    @State private var isSyncing = false
    @State private var syncError: String? = nil
    @State private var showSyncAlert = false
    @State private var syncedCount = 0
    @State private var isServerSyncing = false
    @State private var pollingTask: Task<Void, Never>? = nil
    
    // Reset/Clear State
    @State private var showClearDataConfirmation = false
    
    // Card stack swipe states
    @State private var cardOffset: CGSize = .zero
    
    // Saved Tab search state
    @State private var savedSearchText = ""
    
    // Filters for Discover deck
    var activeDeck: [LocalDiscoveryItem] {
        discoveries.filter { !$0.isSaved && !$0.isSkipped }
    }
    
    // Filtered items in saved list
    var savedItems: [LocalDiscoveryItem] {
        discoveries.filter { item in
            item.isSaved && (savedSearchText.isEmpty ||
                             item.name.localizedCaseInsensitiveContains(savedSearchText) ||
                             item.neighborhood.localizedCaseInsensitiveContains(savedSearchText) ||
                             item.itemDescription.localizedCaseInsensitiveContains(savedSearchText))
        }
    }
    
    var body: some View {
        TabView(selection: $selectedTab) {
            // TAB 1: Discover Card Stack
            discoverView
                .tabItem {
                    Label("Discover", systemImage: "sparkles.rectangle.stack")
                }
                .tag(0)
            
            // TAB 2: Saved Bucket List
            savedView
                .tabItem {
                    Label("Bucket List", systemImage: "bookmark.circle.fill")
                }
                .tag(1)
        }
        .tint(.blue)
        .alert("Sync Status", isPresented: $showSyncAlert) {
            Button("OK", role: .cancel) { }
        } message: {
            if let error = syncError {
                Text("Failed to sync: \(error)")
            } else if syncedCount > 0 {
                Text("Successfully synced \(syncedCount) new discoveries from the pipeline!")
            } else {
                Text("Background sync started! We are crawling DoTheBay, Funcheap, and Secret SF. Tap sync again in a few moments to pull the new gems.")
            }
        }
    }
    
    // MARK: - Discover Card Stack Tab
    
    private var discoverView: some View {
        NavigationStack {
            ZStack {
                // High-end background gradient
                LinearGradient(
                    colors: [Color(.systemGroupedBackground), Color(.systemBackground)],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()
                
                VStack(spacing: 20) {
                    if isServerSyncing {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Crawling & enriching fresh gems in background...")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundColor(.secondary)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(Capsule().fill(Color(.systemGray6)))
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    
                    if activeDeck.isEmpty {
                        emptyDiscoverStateView
                    } else {
                        // Card Stack
                        Spacer()
                        
                        ZStack {
                            // Show back cards with offset and scale to create a 3D deck depth
                            let suffixCards = activeDeck.suffix(3)
                            let count = suffixCards.count
                            
                            ForEach(Array(suffixCards.enumerated()), id: \.element.id) { index, item in
                                let isTopCard = index == count - 1
                                let visualIndex = count - 1 - index // 0 = top card, 1 = middle card, 2 = back card
                                
                                discoveryCard(for: item, isTopCard: isTopCard)
                                    .scaleEffect(isTopCard ? 1.0 : (1.0 - CGFloat(visualIndex) * 0.04))
                                    .offset(y: isTopCard ? 0 : (CGFloat(visualIndex) * -12))
                                    .zIndex(Double(index))
                            }
                        }
                        .frame(height: 540)
                        
                        Spacer()
                        
                        // Action buttons at the bottom (Skip, Undo Skipped, Like)
                        actionButtonsSection
                            .padding(.bottom, 24)
                    }
                }
                .padding(.horizontal)
            }
            .navigationTitle("Find SF Gems")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Menu {
                        Button(action: {
                            showClearDataConfirmation = true
                        }) {
                            Label("Clear Cache & DB...", systemImage: "trash")
                        }
                        
                        Button(action: resetSkippedSwipes) {
                            Label("Reset Skipped Cards", systemImage: "arrow.counterclockwise")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                            .font(.body)
                            .fontWeight(.semibold)
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    syncToolbarButton
                }
            }
            .confirmationDialog(
                "Reset & Clear Data",
                isPresented: $showClearDataConfirmation,
                titleVisibility: .visible
            ) {
                Button("Clear Local App Cache Only", role: .destructive) {
                    clearAllLocalData(alsoClearServer: false)
                }
                Button("Clear Local & Server Database", role: .destructive) {
                    clearAllLocalData(alsoClearServer: true)
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Select how you want to clear the app's cache. Clearing local cache will reset all your swipes and saved list. Clearing local & server will also empty the scraped pipeline backend.")
            }
        }
    }
    
    private var syncToolbarButton: some View {
        Button(action: {
            Task {
                await syncDiscoveries()
            }
        }) {
            HStack(spacing: 4) {
                if isSyncing {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "arrow.triangle.2.circlepath")
                }
                Text("Sync")
            }
            .fontWeight(.semibold)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                Capsule()
                    .fill(isSyncing ? Color.secondary.opacity(0.1) : Color.blue.opacity(0.12))
            )
        }
        .disabled(isSyncing)
    }
    
    private var actionButtonsSection: some View {
        HStack(spacing: 36) {
            // Skip button
            Button(action: {
                if let topCard = activeDeck.last {
                    swipeCard(right: false, item: topCard)
                }
            }) {
                Image(systemName: "xmark")
                    .font(.title2)
                    .fontWeight(.black)
                    .foregroundColor(.red)
                    .frame(width: 60, height: 60)
                    .background(Color(.systemBackground))
                    .clipShape(Circle())
                    .shadow(color: Color.black.opacity(0.08), radius: 8, x: 0, y: 4)
            }
            
            // Reset / Undo skips button
            Button(action: resetSkippedSwipes) {
                Image(systemName: "arrow.counterclockwise")
                    .font(.body)
                    .fontWeight(.bold)
                    .foregroundColor(.yellow)
                    .frame(width: 44, height: 44)
                    .background(Color(.systemBackground))
                    .clipShape(Circle())
                    .shadow(color: Color.black.opacity(0.06), radius: 6, x: 0, y: 3)
            }
            
            // Like / Save button
            Button(action: {
                if let topCard = activeDeck.last {
                    swipeCard(right: true, item: topCard)
                }
            }) {
                Image(systemName: "heart.fill")
                    .font(.title)
                    .foregroundColor(.green)
                    .frame(width: 60, height: 60)
                    .background(Color(.systemBackground))
                    .clipShape(Circle())
                    .shadow(color: Color.black.opacity(0.08), radius: 8, x: 0, y: 4)
            }
        }
    }
    
    private var emptyDiscoverStateView: some View {
        VStack(spacing: 24) {
            Spacer()
            
            Text("DB Total: \(discoveries.count) | Active Deck: \(activeDeck.count) | Syncing: \(isServerSyncing ? "Yes" : "No")")
                .font(.caption)
                .foregroundColor(.gray)
                .padding(.horizontal, 16)
                .padding(.vertical, 6)
                .background(Capsule().fill(Color(.systemGray6)))
            
            ZStack {
                Circle()
                    .fill(Color.blue.opacity(0.1))
                    .frame(width: 140, height: 140)
                
                Image(systemName: "map.fill")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 55, height: 55)
                    .foregroundStyle(
                        LinearGradient(
                            colors: [.blue, .purple],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            }
            
            VStack(spacing: 8) {
                Text("No Gems Left to Swipe")
                    .font(.title2)
                    .fontWeight(.bold)
                
                Text("You've gone through all active discoveries. Tap below to sync fresh listings or reset your skips to review them again.")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
            
            VStack(spacing: 12) {
                Button(action: {
                    Task {
                        await syncDiscoveries()
                    }
                }) {
                    HStack(spacing: 8) {
                        if isSyncing {
                            ProgressView().tint(.white)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text(isSyncing ? "Syncing gems..." : "Sync Fresh Listings")
                            .fontWeight(.bold)
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 28)
                    .padding(.vertical, 14)
                    .background(
                        LinearGradient(colors: [.blue, .purple], startPoint: .leading, endPoint: .trailing)
                    )
                    .clipShape(Capsule())
                    .shadow(color: .blue.opacity(0.3), radius: 8, x: 0, y: 4)
                }
                .disabled(isSyncing)
                
                Button(action: resetSkippedSwipes) {
                    Text("Reset Skipped Cards")
                        .fontWeight(.semibold)
                        .foregroundColor(.blue)
                        .padding(.vertical, 10)
                }
                
                Button(action: {
                    showClearDataConfirmation = true
                }) {
                    Text("Clear Local Cache...")
                        .fontWeight(.semibold)
                        .foregroundColor(.red)
                        .padding(.vertical, 10)
                }
            }
            
            Spacer()
        }
    }
    
    // MARK: - Tinder Card Layout and Gestures
    
    @ViewBuilder
    private func discoveryCard(for item: LocalDiscoveryItem, isTopCard: Bool) -> some View {
        ZStack(alignment: .topLeading) {
            VStack(alignment: .leading, spacing: 18) {
                // Card Media / Category gradient top block
                categoryHeaderView(for: item)
                
                VStack(alignment: .leading, spacing: 14) {
                    // Name
                    Text(item.name)
                        .font(.title2)
                        .fontWeight(.black)
                        .foregroundColor(.primary)
                        .lineLimit(2)
                    
                    // Description hook
                    if !item.isEnriched {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Still loading details...")
                                .font(.subheadline)
                                .italic()
                                .foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 8)
                    } else {
                        Text(item.itemDescription)
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .lineLimit(6)
                            .fixedSize(horizontal: false, vertical: true)
                            .lineSpacing(4)
                    }
                    
                    Spacer()
                    
                    // Info Badges Row (Hours / Website URL)
                    HStack(spacing: 12) {
                        if let hours = item.dateOrHours, !hours.isEmpty {
                            HStack(spacing: 6) {
                                Image(systemName: "clock.badge.checkmark.fill")
                                    .foregroundColor(.blue)
                                    .font(.subheadline)
                                Text(hours)
                                    .font(.caption)
                                    .fontWeight(.medium)
                                    .foregroundColor(.secondary)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(Color(.systemGray6))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                        
                        if let urlString = item.eventURL, let url = URL(string: urlString) {
                            Link(destination: url) {
                                HStack(spacing: 6) {
                                    Image(systemName: "safari.fill")
                                        .foregroundColor(.blue)
                                        .font(.subheadline)
                                    Text("Website")
                                        .font(.caption)
                                        .fontWeight(.bold)
                                        .foregroundColor(.blue)
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(Color.blue.opacity(0.1))
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
            
            // Tinder style stamps: "SAVE" and "SKIP"
            if isTopCard {
                saveBadgeOverlay
                skipBadgeOverlay
            }
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .shadow(color: Color.black.opacity(0.1), radius: 10, x: 0, y: 5)
        .offset(isTopCard ? cardOffset : .zero)
        .rotationEffect(isTopCard ? .degrees(Double(cardOffset.width / 18)) : .zero)
        .gesture(
            isTopCard ? DragGesture()
                .onChanged { gesture in
                    cardOffset = gesture.translation
                }
                .onEnded { gesture in
                    let swipeThreshold: CGFloat = 140
                    if gesture.translation.width > swipeThreshold {
                        // Swipe Right (SAVE)
                        swipeCard(right: true, item: item)
                    } else if gesture.translation.width < -swipeThreshold {
                        // Swipe Left (SKIP)
                        swipeCard(right: false, item: item)
                    } else {
                        // Snap back
                        withAnimation(.spring(response: 0.35, dampingFraction: 0.65)) {
                            cardOffset = .zero
                        }
                    }
                }
            : nil
        )
    }
    
    private var saveBadgeOverlay: some View {
        Text("SAVE")
            .font(.title)
            .fontWeight(.black)
            .foregroundColor(.green)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.green, lineWidth: 4)
            )
            .rotationEffect(.degrees(-15))
            .padding(.leading, 32)
            .padding(.top, 36)
            .opacity(Double(max(0, min(1, cardOffset.width / 80))))
    }
    
    private var skipBadgeOverlay: some View {
        Text("SKIP")
            .font(.title)
            .fontWeight(.black)
            .foregroundColor(.red)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.red, lineWidth: 4)
            )
            .rotationEffect(.degrees(15))
            .padding(.trailing, 32)
            .padding(.top, 36)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .opacity(Double(max(0, min(1, -cardOffset.width / 80))))
    }
    
    @ViewBuilder
    private func categoryHeaderView(for item: LocalDiscoveryItem) -> some View {
        let colors: (Color, Color) = {
            switch item.category.lowercased() {
            case "food":
                return (.orange, .red)
            case "event":
                return (.purple, .blue)
            case "view":
                return (.green, .teal)
            default:
                return (.gray, .secondary)
            }
        }()
        
        ZStack(alignment: .bottomLeading) {
            // Render image with AsyncImage, falling back to category gradient
            if let imageURLString = item.imageURL, let url = URL(string: imageURLString) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(height: 180)
                            .clipped()
                    case .failure, .empty:
                        LinearGradient(
                            colors: [colors.0, colors.1],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                        .frame(height: 180)
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(height: 180)
            } else {
                LinearGradient(
                    colors: [colors.0, colors.1],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .frame(height: 180)
            }
            
            // Readability gradient overlay
            LinearGradient(
                colors: [.clear, .black.opacity(0.5)],
                startPoint: .top,
                endPoint: .bottom
            )
            .frame(height: 180)
            
            HStack {
                Text(item.category.uppercased())
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Color.white.opacity(0.25))
                    .clipShape(Capsule())
                
                Spacer()
                
                Button(action: {
                    let searchQuery = "\(item.name) \(item.neighborhood) San Francisco"
                    if let encodedQuery = searchQuery.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
                       let url = URL(string: "maps://?q=\(encodedQuery)") {
                        UIApplication.shared.open(url)
                    }
                }) {
                    HStack(spacing: 4) {
                        Image(systemName: "mappin.and.ellipse")
                            .foregroundColor(.white)
                            .font(.caption)
                        Text(item.neighborhood)
                            .font(.caption)
                            .fontWeight(.bold)
                            .foregroundColor(.white)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Color.black.opacity(0.35))
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            .padding(16)
        }
    }
    
    // MARK: - Saved Bucket List Tab
    
    private var savedView: some View {
        NavigationStack {
            ZStack {
                Color(.systemGroupedBackground)
                    .ignoresSafeArea()
                
                if savedItems.isEmpty {
                    emptySavedStateView
                } else {
                    List {
                        ForEach(savedItems) { item in
                            savedItemRow(for: item)
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    Button(role: .destructive) {
                                        withAnimation {
                                            item.isSaved = false
                                            // Reset so it is swipable again
                                            item.isSkipped = false
                                            try? modelContext.save()
                                        }
                                    } label: {
                                        Label("Unsave", systemImage: "bookmark.slash")
                                    }
                                }
                        }
                    }
                    .searchable(text: $savedSearchText, prompt: "Search bucket list...")
                }
            }
            .navigationTitle("My Bucket List")
            .toolbar {
                if !savedItems.isEmpty {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button(action: clearSavedList) {
                            Text("Clear All")
                                .foregroundColor(.red)
                        }
                    }
                }
            }
        }
    }
    
    private var emptySavedStateView: some View {
        VStack(spacing: 16) {
            Image(systemName: "bookmark.slash.fill")
                .font(.system(size: 48))
                .foregroundColor(.secondary)
            
            Text("Bucket List Empty")
                .font(.headline)
                .foregroundColor(.secondary)
            
            Text("Find discoveries in the swipe stack and swipe right to save them here.")
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 48)
        }
    }
    
    @ViewBuilder
    private func savedItemRow(for item: LocalDiscoveryItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                let badgeColors: (Color, Color) = {
                    switch item.category.lowercased() {
                    case "food": return (.orange, .red)
                    case "event": return (.purple, .blue)
                    case "view": return (.green, .teal)
                    default: return (.gray, .secondary)
                    }
                }()
                
                Text(item.category.uppercased())
                    .font(.system(size: 9, weight: .bold))
                    .foregroundColor(.white)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        LinearGradient(colors: [badgeColors.0, badgeColors.1], startPoint: .leading, endPoint: .trailing)
                    )
                    .clipShape(Capsule())
                
                Spacer()
                
                Button(action: {
                    let searchQuery = "\(item.name) \(item.neighborhood) San Francisco"
                    if let encodedQuery = searchQuery.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
                       let url = URL(string: "maps://?q=\(encodedQuery)") {
                        UIApplication.shared.open(url)
                    }
                }) {
                    HStack(spacing: 3) {
                        Image(systemName: "mappin.and.ellipse")
                            .font(.caption2)
                        Text(item.neighborhood)
                            .font(.caption)
                            .fontWeight(.medium)
                    }
                    .foregroundColor(.blue)
                }
                .buttonStyle(.plain)
            }
            
            Text(item.name)
                .font(.headline)
                .fontWeight(.bold)
                .foregroundColor(.primary)
            
            if !item.isEnriched {
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Loading description...")
                        .font(.caption)
                        .italic()
                        .foregroundColor(.secondary)
                }
            } else {
                Text(item.itemDescription)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
            
            HStack(spacing: 12) {
                if let hours = item.dateOrHours, !hours.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "calendar")
                            .font(.caption2)
                            .foregroundColor(.blue)
                        Text(hours)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }
                
                if let urlString = item.eventURL, let url = URL(string: urlString) {
                    Link(destination: url) {
                        HStack(spacing: 3) {
                            Image(systemName: "safari")
                                .font(.caption2)
                            Text("View Website")
                                .font(.caption2)
                                .fontWeight(.semibold)
                        }
                        .foregroundColor(.blue)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.top, 2)
        }
        .padding(.vertical, 4)
    }
    
    // MARK: - Swiping Actions / Logic Helpers
    
    private func swipeCard(right: Bool, item: LocalDiscoveryItem) {
        let translationWidth: CGFloat = right ? 800 : -800
        
        // Haptic feedback
        let generator = UIImpactFeedbackGenerator(style: .medium)
        generator.impactOccurred()
        
        withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) {
            cardOffset = CGSize(width: translationWidth, height: 0)
        }
        
        // Small delay matching the slide-out duration before committing data change
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            if right {
                item.isSaved = true
            } else {
                item.isSkipped = true
            }
            try? modelContext.save()
            cardOffset = .zero
        }
    }
    
    private func resetSkippedSwipes() {
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)
        
        withAnimation {
            for item in discoveries {
                if !item.isSaved {
                    item.isSkipped = false
                }
            }
            try? modelContext.save()
        }
    }
    
    private func clearAllLocalData(alsoClearServer: Bool = false) {
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.warning)
        
        withAnimation {
            do {
                try modelContext.delete(model: LocalDiscoveryItem.self)
                try modelContext.save()
            } catch {
                print("Failed to delete local database: \(error)")
            }
        }
        
        if alsoClearServer {
            Task {
                await clearServerDiscoveries()
            }
        }
    }
    
    private func clearServerDiscoveries() async {
        guard let url = URL(string: "http://127.0.0.1:8000/discoveries/clear") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        try? await URLSession.shared.data(for: request)
    }
    
    private func clearSavedList() {
        withAnimation {
            for item in discoveries {
                if item.isSaved {
                    item.isSaved = false
                    item.isSkipped = false
                }
            }
            try? modelContext.save()
        }
    }
    
    // MARK: - API Sync Integration
    
    @MainActor
    private func syncDiscoveries() async {
        isSyncing = true
        syncError = nil
        
        guard let url = URL(string: "http://127.0.0.1:8000/discoveries/scrape-all") else {
            syncError = "Invalid server URL."
            showSyncAlert = true
            isSyncing = false
            return
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                syncError = "Local server is offline or returned an error. Please verify the FastAPI backend is running."
                showSyncAlert = true
                isSyncing = false
                return
            }
            
            let decoder = JSONDecoder()
            let decodedData = try decoder.decode(DiscoveryResponse.self, from: data)
            
            isServerSyncing = decodedData.is_syncing ?? false
            if isServerSyncing {
                startPolling()
            } else {
                stopPolling()
            }
            
            // Query current SwiftData state for deduplication
            let descriptor = FetchDescriptor<LocalDiscoveryItem>()
            let existingItems = try modelContext.fetch(descriptor)
            let existingNames = Set(existingItems.map { $0.name.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) })
            
            var insertedCount = 0
            var seenNames = Set<String>()
            
            for item in decodedData.items {
                let cleanName = item.name.trimmingCharacters(in: .whitespacesAndNewlines)
                let lowercaseName = cleanName.lowercased()
                if !existingNames.contains(lowercaseName) && !seenNames.contains(lowercaseName) {
                    let newItem = LocalDiscoveryItem(
                        name: cleanName,
                        category: item.category,
                        neighborhood: item.neighborhood,
                        itemDescription: item.description,
                        dateOrHours: item.date_or_hours,
                        imageURL: item.image_url,
                        eventURL: item.url,
                        isSaved: false,
                        isSkipped: false, // Default to unswiped
                        dateDiscovered: Date(),
                        isEnriched: item.is_enriched ?? false
                    )
                    modelContext.insert(newItem)
                    seenNames.insert(lowercaseName)
                    insertedCount += 1
                }
            }
            
            if insertedCount > 0 {
                try modelContext.save()
            }
            
            syncedCount = insertedCount
            syncError = nil
            showSyncAlert = true
        } catch {
            print("Decoding/Network Error: \(error)")
            syncError = error.localizedDescription
            showSyncAlert = true
        }
        
        isSyncing = false
    }
    
    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task {
            while isServerSyncing {
                try? await Task.sleep(for: .seconds(5))
                if Task.isCancelled { break }
                await fetchDiscoveriesOnly()
            }
        }
    }
    
    private func stopPolling() {
        pollingTask?.cancel()
        pollingTask = nil
    }
    
    @MainActor
    private func fetchDiscoveriesOnly() async {
        guard let url = URL(string: "http://127.0.0.1:8000/discoveries") else { return }
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else { return }
            
            let decoder = JSONDecoder()
            let decodedData = try decoder.decode(DiscoveryResponse.self, from: data)
            
            isServerSyncing = decodedData.is_syncing ?? false
            
            // Query current SwiftData state to insert or update existing
            let descriptor = FetchDescriptor<LocalDiscoveryItem>()
            let existingItems = try modelContext.fetch(descriptor)
            let existingNames = Set(existingItems.map { $0.name.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) })
            
            var changedCount = 0
            var seenNames = Set<String>()
            
            for item in decodedData.items {
                let cleanName = item.name.trimmingCharacters(in: .whitespacesAndNewlines)
                let lowercaseName = cleanName.lowercased()
                
                if !existingNames.contains(lowercaseName) && !seenNames.contains(lowercaseName) {
                    let newItem = LocalDiscoveryItem(
                        name: cleanName,
                        category: item.category,
                        neighborhood: item.neighborhood,
                        itemDescription: item.description,
                        dateOrHours: item.date_or_hours,
                        imageURL: item.image_url,
                        eventURL: item.url,
                        isSaved: false,
                        isSkipped: false,
                        dateDiscovered: Date(),
                        isEnriched: item.is_enriched ?? false
                    )
                    modelContext.insert(newItem)
                    seenNames.insert(lowercaseName)
                    changedCount += 1
                } else if let existingItem = existingItems.first(where: { $0.name.lowercased() == lowercaseName }) {
                    // Update descriptions/enrichment status if they changed
                    let newEnrichStatus = item.is_enriched ?? false
                    if existingItem.isEnriched != newEnrichStatus || existingItem.itemDescription != item.description {
                        existingItem.itemDescription = item.description
                        existingItem.neighborhood = item.neighborhood
                        existingItem.dateOrHours = item.date_or_hours
                        existingItem.isEnriched = newEnrichStatus
                        if let img = item.image_url, !img.isEmpty {
                            existingItem.imageURL = img
                        }
                        if let u = item.url, !u.isEmpty {
                            existingItem.eventURL = u
                        }
                        changedCount += 1
                    }
                }
            }
            
            if changedCount > 0 {
                try modelContext.save()
            }
            
            if !isServerSyncing {
                stopPolling()
            }
        } catch {
            print("Auto-polling error: \(error)")
        }
    }
}

struct DiscoveryResponse: Codable {
    let items: [DiscoveryItemJSON]
    let is_syncing: Bool?
}

struct DiscoveryItemJSON: Codable {
    let name: String
    let category: String
    let neighborhood: String
    let description: String
    let date_or_hours: String?
    let image_url: String?
    let url: String?
    let is_enriched: Bool?
}

#Preview {
    ContentView()
        .modelContainer(for: LocalDiscoveryItem.self, inMemory: true)
}
