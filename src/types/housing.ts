import type { FeatureCollection } from 'geojson';

export interface ListingsDataset {
  generatedAt: string;
  center: { lat: number; lng: number; name: string };
  maxDriveMinutes: number;
  count: number;
  listings: Listing[];
}

export interface Listing {
  id: string;
  source: string;
  title: string;
  address: string;
  neighborhood: string | null;
  lat: number;
  lng: number;
  rentTotal: number;
  rentPerPerson: number;
  bedrooms: number; // always 4
  bathrooms: number | null;
  sqft: number | null;
  availableDate: string | null;
  leaseTerm: string | null;
  landlord: string;
  parking: string | null;
  petsAllowed: boolean | null;
  petPolicy: string | null;
  amenities: string[];
  description: string;
  photos: string[];
  url: string;
  driveMinutes: number | null;
  walkMinutes: number | null;
  distanceMiles: number | null;
}

export type IsochroneGeoJSON = FeatureCollection;

export type PriceMode = 'perPerson' | 'total';

export type SortOption = 'priceAsc' | 'priceDesc' | 'closest' | 'mostBaths';

export type AvailabilityFilter = 'all' | '2027-2028' | '2026-2027' | 'now';

export interface FilterState {
  search: string;
  priceMode: PriceMode;
  minPrice: number;
  maxPrice: number;
  minBaths: number | null;
  maxDriveMinutes: number | null;
  hasParking: boolean;
  petsOnly: boolean;
  landlord: string;
  availability: AvailabilityFilter;
  shortlistOnly: boolean;
}

export type PriceTier = 'budget' | 'mid' | 'premium';

export interface ShortlistData {
  ids: string[];
  notes: Record<string, string>;
}
