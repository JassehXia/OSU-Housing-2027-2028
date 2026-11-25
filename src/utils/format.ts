import type { AvailabilityFilter, Listing, PriceMode, PriceTier } from '../types/housing';

export const OSU_OVAL: [number, number] = [40.0, -83.0145];

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(Math.round(value));
}

export function getListingPrice(listing: Listing, mode: PriceMode): number {
  return mode === 'perPerson' ? listing.rentPerPerson : listing.rentTotal;
}

/**
 * Classifies a listing into budget / mid / premium based on per-person rent
 * thresholds computed from the dataset (tertiles), with sensible OSU defaults.
 */
export function computePriceThresholds(listings: Listing[]): { low: number; high: number } {
  if (listings.length < 3) {
    return { low: 700, high: 950 };
  }
  const sorted = listings
    .map((l) => l.rentPerPerson)
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => a - b);

  if (sorted.length < 3) {
    return { low: 700, high: 950 };
  }

  const low = sorted[Math.floor(sorted.length / 3)];
  const high = sorted[Math.floor((sorted.length * 2) / 3)];
  return {
    low: Math.round(low),
    high: Math.round(Math.max(high, low + 50)),
  };
}

export function getPriceTier(
  listing: Listing,
  thresholds: { low: number; high: number }
): PriceTier {
  if (listing.rentPerPerson <= thresholds.low) return 'budget';
  if (listing.rentPerPerson <= thresholds.high) return 'mid';
  return 'premium';
}

export const TIER_COLORS: Record<
  PriceTier,
  { fill: string; border: string; badgeBg: string; badgeText: string; label: string }
> = {
  budget: {
    fill: '#059669',
    border: '#047857',
    badgeBg: 'bg-emerald-50 border-emerald-200',
    badgeText: 'text-emerald-700',
    label: 'Budget',
  },
  mid: {
    fill: '#D97706',
    border: '#B45309',
    badgeBg: 'bg-amber-50 border-amber-200',
    badgeText: 'text-amber-700',
    label: 'Mid-Range',
  },
  premium: {
    fill: '#BA0C2F',
    border: '#8E0924',
    badgeBg: 'bg-rose-50 border-rose-200',
    badgeText: 'text-[#BA0C2F]',
    label: 'Higher',
  },
};

export function hasParkingAvailable(listing: Listing): boolean {
  if (!listing.parking) return false;
  const normalized = listing.parking.trim().toLowerCase();
  if (!normalized) return false;
  if (
    normalized === 'none' ||
    normalized === 'no' ||
    normalized === 'no parking' ||
    normalized === 'n/a' ||
    normalized === 'unknown'
  ) {
    return false;
  }
  return true;
}

export function matchesAvailability(
  listing: Listing,
  filter: AvailabilityFilter
): boolean {
  if (filter === 'all') return true;
  const text = `${listing.availableDate ?? ''} ${listing.leaseTerm ?? ''} ${listing.title}`.toLowerCase();

  if (filter === 'now') {
    if (
      text.includes('now') ||
      text.includes('immediate') ||
      text.includes('available today')
    ) {
      return true;
    }
    // Check if ISO date is in the past or within 45 days
    if (listing.availableDate) {
      const parsed = Date.parse(listing.availableDate);
      if (!Number.isNaN(parsed)) {
        const diffDays = (parsed - Date.now()) / (1000 * 60 * 60 * 24);
        if (diffDays <= 45) return true;
      }
    }
    return false;
  }

  if (filter === '2027-2028') {
    return (
      text.includes('2027') ||
      text.includes('27-28') ||
      text.includes('27/28') ||
      text.includes('fall 27')
    );
  }

  if (filter === '2026-2027') {
    return (
      text.includes('2026') ||
      text.includes('26-27') ||
      text.includes('26/27') ||
      text.includes('fall 26')
    );
  }

  return true;
}

export function formatDriveWalk(listing: Listing): string {
  const parts: string[] = [];
  if (listing.driveMinutes != null) {
    parts.push(`${Math.round(listing.driveMinutes)}m drive`);
  }
  if (listing.walkMinutes != null) {
    parts.push(`${Math.round(listing.walkMinutes)}m walk`);
  }
  return parts.join(' · ') || 'Near OSU';
}

export function buildShortlistSummary(
  listings: Listing[],
  notes: Record<string, string>
): string {
  const header = `OSU 4-Bed Housing Shortlist (${listings.length} ${listings.length === 1 ? 'home' : 'homes'})\n${'='.repeat(42)}`;

  const items = listings.map((l, idx) => {
    const rent = `${formatCurrency(l.rentPerPerson)}/person (${formatCurrency(l.rentTotal)}/mo total)`;
    const specs = [
      `${l.bedrooms} bd`,
      l.bathrooms != null ? `${l.bathrooms} ba` : null,
      l.sqft != null ? `${l.sqft.toLocaleString()} sqft` : null,
    ]
      .filter(Boolean)
      .join(' · ');
    const commute = [
      l.driveMinutes != null ? `${Math.round(l.driveMinutes)} min drive` : null,
      l.walkMinutes != null ? `${Math.round(l.walkMinutes)} min walk` : null,
    ]
      .filter(Boolean)
      .join(' / ');
    const note = notes[l.id]?.trim();

    const lines = [
      `${idx + 1}. ${l.address || l.title}${l.neighborhood ? ` (${l.neighborhood})` : ''}`,
      `   Rent: ${rent}`,
      `   Specs: ${specs}${commute ? ` | ${commute} to OSU` : ''}`,
      `   Landlord: ${l.landlord}${l.availableDate ? ` | Avail: ${l.availableDate}` : ''}`,
    ];
    if (note) {
      lines.push(`   Notes: ${note}`);
    }
    if (l.url) {
      lines.push(`   Link: ${l.url}`);
    }
    return lines.join('\n');
  });

  return `${header}\n\n${items.join('\n\n')}`;
}
