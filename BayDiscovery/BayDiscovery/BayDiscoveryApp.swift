//
//  BayDiscoveryApp.swift
//  BayDiscovery
//
//  Created by Leonardo Flores Gonzalez on 6/19/26.
//

import SwiftUI
import SwiftData

@main
struct BayDiscoveryApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: [LocalDiscoveryItem.self])
    }
}
