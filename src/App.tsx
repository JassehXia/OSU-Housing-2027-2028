import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { HousingMap } from './components/HousingMap';
import { ListingDetailDrawer } from './components/ListingDetailDrawer';
import { ShortlistModal } from './components/ShortlistModal';
import { Sidebar } from './components/Sidebar';
import { useHousingData } from './hooks/useHousingData';
import { useShortlist } from './hooks/useShortlist';
import type { FilterState, Listing, PriceMode, SortOption } from './types/housing';
import {
  computePriceThresholds,
  getListingPrice,
  hasParkingAvailable,
  matchesAvailability,
  OSU_OVAL,
} from './utils/format';

function computePriceBounds(
  listings: Listing[],
  mode: PriceMode
): { min: number; max: number } {
  const step = mode === 'perPerson' ? 25 : 100;
  const prices = listings
    .map((l) => getListingPrice(l, mode))
    .filter((p) => Number.isFinite(p) && p > 0);

  if (prices.length === 0) {
    return mode === 'perPerson' ? { min: 400, max: 2000 } : { min: 1600, max: 8000 };
  }

  const rawMin = Math.min(...prices);
  const rawMax = Math.max(...prices);
  const min = Math.floor(rawMin / step) * step;
  const max = Math.ceil(rawMax / step) * step;
  return { min, max: Math.max(max, min + step) };
}

export default function App() {
  const { dataset, isochrone, loading, error } = useHousingData();
  const {
    shortlistIds,
    notes,
    toggleShortlist,
    setNote,
    isShortlisted,
    getNote,
  } = useShortlist();

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showBoundary, setShowBoundary] = useState(true);
  const [shortlistModalOpen, setShortlistModalOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortOption>('priceAsc');
  const [flyToRequest, setFlyToRequest] = useState<{
    lat: number;
    lng: number;
    seq: number;
  } | null>(null);

  const [filters, setFilters] = useState<FilterState>({
    search: '',
    priceMode: 'perPerson',
    minPrice: 0,
    maxPrice: 5000,
    minBaths: null,
    maxDriveMinutes: null,
    hasParking: false,
    petsOnly: false,
    landlord: 'all',
    availability: 'all',
    shortlistOnly: false,
  });

  const allListings = useMemo(() => dataset?.listings ?? [], [dataset]);

  const mapCenter = useMemo<[number, number]>(() => {
    if (
      dataset?.center &&
      Number.isFinite(dataset.center.lat) &&
      Number.isFinite(dataset.center.lng)
    ) {
      return [dataset.center.lat, dataset.center.lng];
    }
    return OSU_OVAL;
  }, [dataset]);

  const priceThresholds = useMemo(
    () => computePriceThresholds(allListings),
    [allListings]
  );

  const priceBounds = useMemo(
    () => computePriceBounds(allListings, filters.priceMode),
    [allListings, filters.priceMode]
  );

  // Initialize price slider bounds once dataset loads
  useEffect(() => {
    if (allListings.length === 0) return;
    const bounds = computePriceBounds(allListings, 'perPerson');
    setFilters((prev) => ({
      ...prev,
      minPrice: bounds.min,
      maxPrice: bounds.max,
    }));
  }, [allListings]);

  const landlords = useMemo(() => {
    const set = new Set<string>();
    for (const l of allListings) {
      if (l.landlord && l.landlord.trim()) {
        set.add(l.landlord.trim());
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [allListings]);

  const handleChangePriceMode = useCallback(
    (mode: PriceMode) => {
      const nextBounds = computePriceBounds(allListings, mode);
      setFilters((prev) => ({
        ...prev,
        priceMode: mode,
        minPrice: nextBounds.min,
        maxPrice: nextBounds.max,
      }));
    },
    [allListings]
  );

  const handleResetFilters = useCallback(() => {
    const bounds = computePriceBounds(allListings, filters.priceMode);
    setFilters((prev) => ({
      search: '',
      priceMode: prev.priceMode,
      minPrice: bounds.min,
      maxPrice: bounds.max,
      minBaths: null,
      maxDriveMinutes: null,
      hasParking: false,
      petsOnly: false,
      landlord: 'all',
      availability: 'all',
      shortlistOnly: false,
    }));
  }, [allListings, filters.priceMode]);

  const hasActiveFilters = useMemo(() => {
    return (
      filters.search.trim() !== '' ||
      filters.minPrice > priceBounds.min ||
      filters.maxPrice < priceBounds.max ||
      filters.minBaths !== null ||
      filters.maxDriveMinutes !== null ||
      filters.hasParking ||
      filters.petsOnly ||
      filters.landlord !== 'all' ||
      filters.availability !== 'all' ||
      filters.shortlistOnly
    );
  }, [filters, priceBounds]);

  const filteredListings = useMemo(() => {
    const query = filters.search.trim().toLowerCase();
    const shortlistSet = new Set(shortlistIds);

    const matched = allListings.filter((l) => {
      const price = getListingPrice(l, filters.priceMode);
      if (price < filters.minPrice || price > filters.maxPrice) return false;

      if (filters.minBaths !== null) {
        if (l.bathrooms == null || l.bathrooms < filters.minBaths) return false;
      }

      if (filters.maxDriveMinutes !== null) {
        if (l.driveMinutes == null || l.driveMinutes > filters.maxDriveMinutes) {
          return false;
        }
      }

      if (filters.hasParking && !hasParkingAvailable(l)) return false;
      if (filters.petsOnly && l.petsAllowed !== true) return false;
      if (filters.landlord !== 'all' && l.landlord !== filters.landlord) {
        return false;
      }
      if (!matchesAvailability(l, filters.availability)) return false;
      if (filters.shortlistOnly && !shortlistSet.has(l.id)) return false;

      if (query) {
        const haystack = [
          l.address,
          l.title,
          l.neighborhood ?? '',
          l.landlord,
          l.source,
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(query)) return false;
      }

      return true;
    });

    return [...matched].sort((a, b) => {
      switch (sortBy) {
        case 'priceAsc':
          return (
            getListingPrice(a, filters.priceMode) -
            getListingPrice(b, filters.priceMode)
          );
        case 'priceDesc':
          return (
            getListingPrice(b, filters.priceMode) -
            getListingPrice(a, filters.priceMode)
          );
        case 'closest': {
          const aDist = a.driveMinutes ?? a.distanceMiles ?? Number.POSITIVE_INFINITY;
          const bDist = b.driveMinutes ?? b.distanceMiles ?? Number.POSITIVE_INFINITY;
          return aDist - bDist;
        }
        case 'mostBaths':
          return (b.bathrooms ?? -1) - (a.bathrooms ?? -1);
      }
    });
  }, [allListings, filters, shortlistIds, sortBy]);

  const selectedListing = useMemo(
    () => allListings.find((l) => l.id === selectedId) ?? null,
    [allListings, selectedId]
  );

  const shortlistedListings = useMemo(() => {
    const map = new Map(allListings.map((l) => [l.id, l]));
    return shortlistIds
      .map((id) => map.get(id))
      .filter((item): item is Listing => Boolean(item));
  }, [allListings, shortlistIds]);

  const handleSelectFromList = useCallback((listing: Listing) => {
    setSelectedId(listing.id);
    if (Number.isFinite(listing.lat) && Number.isFinite(listing.lng)) {
      setFlyToRequest((prev) => ({
        lat: listing.lat,
        lng: listing.lng,
        seq: (prev?.seq ?? 0) + 1,
      }));
    }
  }, []);

  return (
    <div className="relative flex h-screen w-screen overflow-hidden bg-slate-100">
      {/* Collapsible Left Sidebar */}
      <Sidebar
        open={sidebarOpen}
        onToggleOpen={() => setSidebarOpen((v) => !v)}
        totalCount={allListings.length}
        listings={filteredListings}
        filters={filters}
        priceBounds={priceBounds}
        priceThresholds={priceThresholds}
        landlords={landlords}
        sortBy={sortBy}
        selectedId={selectedId}
        hoveredId={hoveredId}
        shortlistIds={shortlistIds}
        hasActiveFilters={hasActiveFilters}
        onChangeFilters={setFilters}
        onChangePriceMode={handleChangePriceMode}
        onResetFilters={handleResetFilters}
        onChangeSort={setSortBy}
        onSelectListing={handleSelectFromList}
        onHoverListing={setHoveredId}
        onToggleShortlist={toggleShortlist}
        onOpenShortlistModal={() => setShortlistModalOpen(true)}
      />

      {/* Main Full-Bleed Map Area */}
      <main className="relative flex-1 overflow-hidden">
        <HousingMap
          listings={filteredListings}
          isochrone={isochrone}
          center={mapCenter}
          selectedId={selectedId}
          hoveredId={hoveredId}
          shortlistIds={shortlistIds}
          priceMode={filters.priceMode}
          priceThresholds={priceThresholds}
          showBoundary={showBoundary}
          onToggleBoundary={() => setShowBoundary((v) => !v)}
          onSelectListing={setSelectedId}
          onHoverListing={setHoveredId}
          flyToRequest={flyToRequest}
          sidebarOpen={sidebarOpen}
          detailOpen={Boolean(selectedListing)}
        />

        {/* Loading Overlay */}
        {loading && (
          <div className="pointer-events-none absolute inset-0 z-[600] flex items-center justify-center bg-white/70 backdrop-blur-xs">
            <div className="flex items-center gap-2.5 rounded-2xl border border-slate-200 bg-white px-5 py-3.5 shadow-lg">
              <Loader2 className="h-5 w-5 animate-spin text-[#BA0C2F]" />
              <span className="text-sm font-semibold text-slate-800">
                Loading OSU 4-bedroom listings…
              </span>
            </div>
          </div>
        )}

        {/* Error Banner */}
        {error && !loading && (
          <div className="absolute top-16 left-1/2 z-[600] -translate-x-1/2">
            <div className="flex items-center gap-2.5 rounded-xl border border-rose-200 bg-white px-4 py-3 text-xs font-medium text-rose-700 shadow-lg">
              <AlertCircle className="h-4 w-4 shrink-0 text-[#BA0C2F]" />
              <span>{error} — make sure `/data/listings.json` is available.</span>
            </div>
          </div>
        )}
      </main>

      {/* Right Listing Detail Drawer */}
      <ListingDetailDrawer
        listing={selectedListing}
        priceThresholds={priceThresholds}
        isShortlisted={selectedListing ? isShortlisted(selectedListing.id) : false}
        note={selectedListing ? getNote(selectedListing.id) : ''}
        onClose={() => setSelectedId(null)}
        onToggleShortlist={toggleShortlist}
        onChangeNote={setNote}
      />

      {/* Shortlist & Group Chat Export Modal */}
      <ShortlistModal
        open={shortlistModalOpen}
        listings={shortlistedListings}
        notes={notes}
        onClose={() => setShortlistModalOpen(false)}
        onSelectListing={handleSelectFromList}
        onRemoveShortlist={toggleShortlist}
        onChangeNote={setNote}
      />
    </div>
  );
}
