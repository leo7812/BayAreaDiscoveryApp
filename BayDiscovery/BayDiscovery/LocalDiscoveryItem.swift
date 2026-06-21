//
//  LocalDiscoveryItem.swift
//  BayDiscovery
//
//  Created by Antigravity on 6/19/26.
//

import Foundation
import SwiftData

@Model
final class LocalDiscoveryItem {
    @Attribute(.unique) var name: String
    var category: String // Expected values: "Food", "Event", "View"
    var neighborhood: String
    var itemDescription: String
    var dateOrHours: String?
    var imageURL: String?
    var eventURL: String?
    var isSaved: Bool
    var isSkipped: Bool
    var dateDiscovered: Date
    var isEnriched: Bool
    
    init(
        name: String,
        category: String,
        neighborhood: String,
        itemDescription: String,
        dateOrHours: String? = nil,
        imageURL: String? = nil,
        eventURL: String? = nil,
        isSaved: Bool = false,
        isSkipped: Bool = false,
        dateDiscovered: Date = Date(),
        isEnriched: Bool = false
    ) {
        self.name = name
        self.category = category
        self.neighborhood = neighborhood
        self.itemDescription = itemDescription
        self.dateOrHours = dateOrHours
        self.imageURL = imageURL
        self.eventURL = eventURL
        self.isSaved = isSaved
        self.isSkipped = isSkipped
        self.dateDiscovered = dateDiscovered
        self.isEnriched = isEnriched
    }
}
