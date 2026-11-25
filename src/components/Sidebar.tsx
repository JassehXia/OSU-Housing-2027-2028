import { useState } from 'react';
import {
  ArrowUpDown,
  Car,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Heart,
  Home,
  PawPrint,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import type {
  AvailabilityFilter,
  FilterState,
  Listing,
  PriceMode,
  SortOption,
} from '../types/housing';
import {
  formatCurrency,
  formatDriveWalk,
  getListingPrice,
  getPriceTier,
  TIER_COLORS,
} from '../utils/format';

interface SidebarProps {
  open: boolean;
  onToggleOpen: () => void;
  totalCount: number;
  listings: Listing[];
  filters: FilterState;
  priceBounds: { min: number; max: number };
  priceThresholds: { low: number; high: number };
  landlords: string[];
  sortBy: SortOption;
  selectedId: string | null;
  hoveredId: string | null;
  shortlistIds: string[];
  hasActiveFilters: boolean;
  onChangeFilters: (updater: (prev: FilterState) => FilterState) => void;
  onChangePriceMode: (mode: PriceMode) => void;
  onResetFilters: () => void;
  onChangeSort: (sort: SortOption) => void;
  onSelectListing: (listing: Listing) => void;
  onHoverListing: (id: string | null) => void;
  onToggleShortlist: (id: string) => void;
  onOpenShortlistModal: () => void;
}

const BATH_OPTIONS: Array<{ label: string; value: number | null }> = [
  { label: 'Any', value: null },
  { label: '1+', value: 1 },
  { label: '1.5+', value: 1.5 },
  { label: '2+', value: 2 },
  { label: '3+', value: 3 },
];

const DRIVE_OPTIONS: Array<{ label: string; value: number | null }> = [
  { label: 'Any (≤20m)', value: null },
  { label: '≤5m', value: 5 },
  { label: '≤10m', value: 10 },
  { label: '≤15m', value: 15 },
];

export function Sidebar({
  open,
  onToggleOpen,
  totalCount,
  listings,
  filters,
  priceBounds,
  priceThresholds,
  landlords,
  sortBy,
  selectedId,
  hoveredId,
  shortlistIds,
  hasActiveFilters,
  onChangeFilters,
  onChangePriceMode,
  onResetFilters,
  onChangeSort,
  onSelectListing,
  onHoverListing,
  onToggleShortlist,
  onOpenShortlistModal,
}: SidebarProps) {
  const [filtersExpanded, setFiltersExpanded] = useState(true);
  const shortlistSet = new Set(shortlistIds);

  const step = filters.priceMode === 'perPerson' ? 25 : 100;
  const safeSpan = Math.max(priceBounds.max - priceBounds.min, 1);
  const minPct = Math.max(
    0,
    Math.min(100, ((filters.minPrice - priceBounds.min) / safeSpan) * 100)
  );
  const maxPct = Math.max(
    0,
    Math.min(100, ((filters.maxPrice - priceBounds.min) / safeSpan) * 100)
  );

  return (
    <>
      {/* Collapsed reopen tab */}
      {!open && (
        <button
          type="button"
          onClick={onToggleOpen}
          className="fixed top-4 left-4 z-[500] inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-3.5 py-2 text-xs font-semibold text-slate-800 shadow-md backdrop-blur-md transition hover:border-[#BA0C2F]/30 hover:text-[#BA0C2F]"
        >
          <span className="h-2.5 w-2.5 rounded-full bg-[#BA0C2F]" />
          <span>OSU 4-Bed Map</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
            {listings.length}
          </span>
          <ChevronRight className="h-4 w-4 text-slate-400" />
        </button>
      )}

      {/* Main Sidebar Panel */}
      <aside
        className={`relative z-[500] flex h-full shrink-0 flex-col border-r border-slate-200/90 bg-white shadow-xl transition-all duration-200 ease-out ${
          open ? 'w-full max-w-[392px] sm:w-[392px]' : 'w-0 overflow-hidden border-r-0'
        }`}
      >
        {/* Top Brand Header */}
        <div className="flex items-center justify-between gap-2 border-b border-slate-200/80 px-4 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[#BA0C2F] text-xs font-extrabold text-white shadow-xs">
                O
              </span>
              <h1 className="truncate text-[15px] font-bold tracking-tight text-slate-900">
                OSU 4-Bed Housing Map
              </h1>
            </div>
            <p className="mt-0.5 text-xs text-slate-500">
              Showing{' '}
              <span className="font-semibold text-slate-800">{listings.length}</span> of{' '}
              <span className="font-medium text-slate-700">{totalCount}</span> 4BR listings
            </p>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onOpenShortlistModal}
              title="View shortlist & export for group chat"
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition ${
                shortlistIds.length > 0
                  ? 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100'
                  : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Heart
                className={`h-3.5 w-3.5 ${
                  shortlistIds.length > 0 ? 'fill-[#BA0C2F] text-[#BA0C2F]' : 'text-slate-400'
                }`}
              />
              <span>{shortlistIds.length}</span>
            </button>

            <button
              type="button"
              onClick={onToggleOpen}
              title="Collapse sidebar"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Search + Filter Toggle Bar */}
        <div className="border-b border-slate-100 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={filters.search}
                onChange={(e) =>
                  onChangeFilters((prev) => ({ ...prev, search: e.target.value }))
                }
                placeholder="Address, neighborhood, landlord..."
                className="w-full rounded-lg border border-slate-200 bg-slate-50/70 py-1.5 pr-7 pl-8 text-xs text-slate-800 placeholder:text-slate-400 focus:border-[#BA0C2F]/50 focus:bg-white focus:ring-2 focus:ring-[#BA0C2F]/15 focus:outline-none"
              />
              {filters.search && (
                <button
                  type="button"
                  onClick={() => onChangeFilters((prev) => ({ ...prev, search: '' }))}
                  className="absolute top-1/2 right-2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => setFiltersExpanded((v) => !v)}
              className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
                filtersExpanded
                  ? 'border-slate-300 bg-slate-100 text-slate-800'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              <span>Filters</span>
              {filtersExpanded ? (
                <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              )}
            </button>
          </div>
        </div>

        {/* Collapsible Filter Controls */}
        {filtersExpanded && (
          <div className="max-h-[44%] shrink-0 space-y-3.5 overflow-y-auto border-b border-slate-200/80 bg-slate-50/50 px-4 py-3 thin-scrollbar">
            {/* Price Filter */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
                  Monthly Rent
                </span>
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-[11px] font-semibold">
                  <button
                    type="button"
                    onClick={() => onChangePriceMode('perPerson')}
                    className={`rounded-md px-2 py-0.5 transition ${
                      filters.priceMode === 'perPerson'
                        ? 'bg-[#BA0C2F] text-white shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    Per Person
                  </button>
                  <button
                    type="button"
                    onClick={() => onChangePriceMode('total')}
                    className={`rounded-md px-2 py-0.5 transition ${
                      filters.priceMode === 'total'
                        ? 'bg-[#BA0C2F] text-white shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    Total Rent
                  </button>
                </div>
              </div>

              {/* Dual-handle slider */}
              <div className="relative mt-1 mb-2.5 flex h-5 items-center">
                <div className="h-1.5 w-full rounded-full bg-slate-200" />
                <div
                  className="absolute h-1.5 rounded-full bg-[#BA0C2F]"
                  style={{
                    left: `${minPct}%`,
                    width: `${Math.max(0, maxPct - minPct)}%`,
                  }}
                />
                <input
                  type="range"
                  min={priceBounds.min}
                  max={priceBounds.max}
                  step={step}
                  value={filters.minPrice}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    onChangeFilters((prev) => ({
                      ...prev,
                      minPrice: Math.min(val, prev.maxPrice),
                    }));
                  }}
                  aria-label="Minimum rent"
                  className="dual-range absolute inset-0 h-5 w-full"
                />
                <input
                  type="range"
                  min={priceBounds.min}
                  max={priceBounds.max}
                  step={step}
                  value={filters.maxPrice}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    onChangeFilters((prev) => ({
                      ...prev,
                      maxPrice: Math.max(val, prev.minPrice),
                    }));
                  }}
                  aria-label="Maximum rent"
                  className="dual-range absolute inset-0 h-5 w-full"
                />
              </div>

              {/* Numeric quick inputs */}
              <div className="grid grid-cols-2 gap-2">
                <label className="relative block">
                  <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-[11px] font-medium text-slate-400">
                    Min $
                  </span>
                  <input
                    type="number"
                    min={priceBounds.min}
                    max={filters.maxPrice}
                    step={step}
                    value={filters.minPrice}
                    onChange={(e) => {
                      const val = Number(e.target.value);
                      if (!Number.isNaN(val)) {
                        onChangeFilters((prev) => ({ ...prev, minPrice: val }));
                      }
                    }}
                    className="w-full rounded-lg border border-slate-200 bg-white py-1 pr-2 pl-11 text-xs font-semibold text-slate-800 focus:border-[#BA0C2F]/50 focus:outline-none"
                  />
                </label>
                <label className="relative block">
                  <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-[11px] font-medium text-slate-400">
                    Max $
                  </span>
                  <input
                    type="number"
                    min={filters.minPrice}
                    max={priceBounds.max}
                    step={step}
                    value={filters.maxPrice}
                    onChange={(e) => {
                      const val = Number(e.target.value);
                      if (!Number.isNaN(val)) {
                        onChangeFilters((prev) => ({ ...prev, maxPrice: val }));
                      }
                    }}
                    className="w-full rounded-lg border border-slate-200 bg-white py-1 pr-2 pl-12 text-xs font-semibold text-slate-800 focus:border-[#BA0C2F]/50 focus:outline-none"
                  />
                </label>
              </div>
            </div>

            {/* Bathrooms */}
            <div>
              <span className="mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
                Bathrooms
              </span>
              <div className="grid grid-cols-5 gap-1">
                {BATH_OPTIONS.map((opt) => {
                  const active = filters.minBaths === opt.value;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      onClick={() =>
                        onChangeFilters((prev) => ({ ...prev, minBaths: opt.value }))
                      }
                      className={`rounded-lg border py-1 text-xs font-semibold transition ${
                        active
                          ? 'border-[#BA0C2F] bg-[#BA0C2F] text-white'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Max Drive Time */}
            <div>
              <span className="mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
                Max Drive to OSU Oval
              </span>
              <div className="grid grid-cols-4 gap-1">
                {DRIVE_OPTIONS.map((opt) => {
                  const active = filters.maxDriveMinutes === opt.value;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      onClick={() =>
                        onChangeFilters((prev) => ({
                          ...prev,
                          maxDriveMinutes: opt.value,
                        }))
                      }
                      className={`rounded-lg border py-1 text-[11px] font-semibold transition ${
                        active
                          ? 'border-[#BA0C2F] bg-[#BA0C2F] text-white'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Quick Feature Toggles */}
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() =>
                  onChangeFilters((prev) => ({
                    ...prev,
                    hasParking: !prev.hasParking,
                  }))
                }
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold transition ${
                  filters.hasParking
                    ? 'border-[#BA0C2F] bg-[#FDF2F4] text-[#BA0C2F]'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                }`}
              >
                <Car className="h-3.5 w-3.5" />
                <span>Has Parking</span>
              </button>

              <button
                type="button"
                onClick={() =>
                  onChangeFilters((prev) => ({
                    ...prev,
                    petsOnly: !prev.petsOnly,
                  }))
                }
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold transition ${
                  filters.petsOnly
                    ? 'border-[#BA0C2F] bg-[#FDF2F4] text-[#BA0C2F]'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                }`}
              >
                <PawPrint className="h-3.5 w-3.5" />
                <span>Pet Friendly</span>
              </button>

              <button
                type="button"
                onClick={() =>
                  onChangeFilters((prev) => ({
                    ...prev,
                    shortlistOnly: !prev.shortlistOnly,
                  }))
                }
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold transition ${
                  filters.shortlistOnly
                    ? 'border-[#BA0C2F] bg-[#BA0C2F] text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                }`}
              >
                <Heart
                  className={`h-3.5 w-3.5 ${
                    filters.shortlistOnly ? 'fill-white text-white' : 'text-[#BA0C2F]'
                  }`}
                />
                <span>Shortlist ({shortlistIds.length})</span>
              </button>
            </div>

            {/* Availability & Landlord Dropdowns */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-slate-500">
                  Availability
                </label>
                <select
                  value={filters.availability}
                  onChange={(e) =>
                    onChangeFilters((prev) => ({
                      ...prev,
                      availability: e.target.value as AvailabilityFilter,
                    }))
                  }
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 focus:border-[#BA0C2F]/50 focus:outline-none"
                >
                  <option value="all">All Dates</option>
                  <option value="2027-2028">2027–2028 / Fall 2027</option>
                  <option value="2026-2027">2026–2027 / Fall 2026</option>
                  <option value="now">Available Now</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-semibold text-slate-500">
                  Landlord / Source
                </label>
                <select
                  value={filters.landlord}
                  onChange={(e) =>
                    onChangeFilters((prev) => ({ ...prev, landlord: e.target.value }))
                  }
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 focus:border-[#BA0C2F]/50 focus:outline-none"
                >
                  <option value="all">All Landlords</option>
                  {landlords.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {hasActiveFilters && (
              <button
                type="button"
                onClick={onResetFilters}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                <span>Reset All Filters</span>
              </button>
            )}
          </div>
        )}

        {/* Sort Bar */}
        <div className="flex items-center justify-between border-b border-slate-200/70 bg-white px-4 py-2">
          <span className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
            Results ({listings.length})
          </span>
          <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
            <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={sortBy}
              onChange={(e) => onChangeSort(e.target.value as SortOption)}
              className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700 focus:border-[#BA0C2F]/50 focus:outline-none"
            >
              <option value="priceAsc">Price: Low → High</option>
              <option value="priceDesc">Price: High → Low</option>
              <option value="closest">Closest to Campus</option>
              <option value="mostBaths">Most Baths</option>
            </select>
          </label>
        </div>

        {/* Scrollable Listings Feed */}
        <div className="flex-1 overflow-y-auto p-3 thin-scrollbar">
          {listings.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 py-10 text-center">
              <Home className="h-7 w-7 text-slate-300" />
              <p className="mt-2 text-sm font-semibold text-slate-700">
                No matching 4BR listings
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Try widening your price range or clearing a filter.
              </p>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={onResetFilters}
                  className="mt-3 rounded-lg bg-[#BA0C2F] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#960925]"
                >
                  Reset Filters
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {listings.map((listing) => {
                const isSelected = listing.id === selectedId;
                const isHovered = listing.id === hoveredId;
                const isSaved = shortlistSet.has(listing.id);
                const tier = getPriceTier(listing, priceThresholds);
                const tierStyle = TIER_COLORS[tier];
                const primaryPrice = getListingPrice(listing, filters.priceMode);

                return (
                  <div
                    key={listing.id}
                    onMouseEnter={() => onHoverListing(listing.id)}
                    onMouseLeave={() => onHoverListing(null)}
                    onClick={() => onSelectListing(listing)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onSelectListing(listing);
                      }
                    }}
                    className={`group flex cursor-pointer gap-3 rounded-xl border p-2.5 transition ${
                      isSelected
                        ? 'border-[#BA0C2F] bg-[#FDF2F4]/60 ring-2 ring-[#BA0C2F]/15'
                        : isHovered
                          ? 'border-slate-300 bg-slate-50 shadow-xs'
                          : 'border-slate-200/80 bg-white hover:border-slate-300 hover:bg-slate-50/60'
                    }`}
                  >
                    {/* Thumbnail */}
                    <div className="relative h-20 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-100">
                      {listing.photos[0] ? (
                        <img
                          src={listing.photos[0]}
                          alt={listing.address || listing.title}
                          loading="lazy"
                          className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
                          onError={(e) => {
                            (e.currentTarget as HTMLImageElement).style.display = 'none';
                          }}
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 text-slate-400">
                          <Home className="h-5 w-5" />
                        </div>
                      )}
                      <span
                        className="absolute bottom-1.5 left-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-white"
                        style={{ backgroundColor: tierStyle.fill }}
                        title={`${tierStyle.label} price tier`}
                      />
                    </div>

                    {/* Content */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-1.5">
                        <div className="min-w-0">
                          <div className="flex items-baseline gap-1.5">
                            <span className="text-sm font-bold text-slate-900">
                              {formatCurrency(primaryPrice)}
                            </span>
                            <span className="text-[11px] font-medium text-slate-500">
                              {filters.priceMode === 'perPerson' ? '/person' : '/mo'}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-500">
                            {filters.priceMode === 'perPerson'
                              ? `${formatCurrency(listing.rentTotal)}/mo total`
                              : `${formatCurrency(listing.rentPerPerson)}/person`}
                          </p>
                        </div>

                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onToggleShortlist(listing.id);
                          }}
                          title={isSaved ? 'Remove from shortlist' : 'Add to shortlist'}
                          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition ${
                            isSaved
                              ? 'bg-[#FDF2F4] text-[#BA0C2F]'
                              : 'text-slate-400 hover:bg-slate-100 hover:text-[#BA0C2F]'
                          }`}
                        >
                          <Heart
                            className={`h-3.5 w-3.5 ${isSaved ? 'fill-[#BA0C2F]' : ''}`}
                          />
                        </button>
                      </div>

                      <p className="mt-1 truncate text-xs font-semibold text-slate-800">
                        {listing.address || listing.title}
                      </p>

                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
                        <span className="font-medium text-slate-700">
                          {listing.bedrooms} bd
                          {listing.bathrooms != null ? ` · ${listing.bathrooms} ba` : ''}
                        </span>
                        {listing.sqft != null && (
                          <span>{listing.sqft.toLocaleString()} sqft</span>
                        )}
                      </div>

                      <div className="mt-1 flex items-center justify-between gap-1 text-[11px]">
                        <span className="truncate text-slate-500">
                          {listing.neighborhood || listing.landlord}
                        </span>
                        <span className="shrink-0 font-medium text-slate-600">
                          {formatDriveWalk(listing)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
