"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Card } from "@/components/atoms/Card";
import { TextField } from "@/components/atoms/TextField";
import { apiClient, ApiError } from "@/lib/api-client";

interface BrandingResponse {
  logo_asset_id: string | null;
  footer_year_default: string | null;
}

export function BrandingSettingsTemplate() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [branding, setBranding] = useState<BrandingResponse | null>(null);
  const [logoPreviewUrl, setLogoPreviewUrl] = useState<string | null>(null);
  const [footerYear, setFooterYear] = useState("");
  const [isSavingYear, setIsSavingYear] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<BrandingResponse>("/branding")
      .then((data) => {
        setBranding(data);
        setFooterYear(data.footer_year_default ?? "");
      })
      .catch(() => setBranding({ logo_asset_id: null, footer_year_default: null }));
  }, []);

  useEffect(() => {
    // No synchronous setState here when the logo was reset — the JSX below
    // gates on `branding?.logo_asset_id` directly, so an existing
    // (now-stale) preview URL simply stops being shown without needing a
    // state write in this branch.
    if (!branding?.logo_asset_id) return;
    let cancelled = false;
    apiClient
      .get<{ url: string }>(`/assets/${branding.logo_asset_id}/presigned-url`)
      .then((res) => {
        if (!cancelled) setLogoPreviewUrl(res.url);
      })
      .catch(() => {
        if (!cancelled) setLogoPreviewUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [branding?.logo_asset_id]);

  async function handleSaveFooterYear(event: React.FormEvent) {
    event.preventDefault();
    setIsSavingYear(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await apiClient.put<BrandingResponse>("/branding", { footer_year_default: footerYear || null });
      setBranding(updated);
      setSavedMessage("Saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setIsSavingYear(false);
    }
  }

  async function handleUploadLogo(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setError(null);
    setSavedMessage(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const updated = await apiClient.postForm<BrandingResponse>("/branding/logo", formData);
      setBranding(updated);
      setSavedMessage("Logo updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to upload logo");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleResetLogo() {
    setIsResetting(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await apiClient.delete<BrandingResponse>("/branding/logo");
      setBranding(updated);
      setSavedMessage("Reverted to the default ERA InfoTech logo.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to reset logo");
    } finally {
      setIsResetting(false);
    }
  }

  return (
    <div className="space-y-8 pt-6">
      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">Document branding</h2>
        <p className="max-w-lg text-sm leading-relaxed text-ink-muted">
          Replace the logo shown in every generated document&apos;s footer, and set the default footer
          copyright year (still overridable per generation). Leave blank to keep the org template&apos;s own
          defaults.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </p>
      )}
      {savedMessage && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">{savedMessage}</p>}

      <Card className="max-w-xl space-y-4">
        <h2 className="text-sm font-medium text-ink">Footer logo</h2>
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-40 items-center justify-center rounded-md border border-line-strong bg-surface-raised">
            {branding?.logo_asset_id && logoPreviewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoPreviewUrl} alt="Current footer logo" className="max-h-14 max-w-36 object-contain" />
            ) : (
              <span className="text-xs text-ink-faint">Default ERA logo</span>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg"
              onChange={handleUploadLogo}
              disabled={isUploading}
              className="text-xs text-ink-faint file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-accent-ink hover:file:opacity-90"
            />
            {branding?.logo_asset_id && (
              <button
                type="button"
                onClick={handleResetLogo}
                disabled={isResetting}
                className="self-start text-xs font-medium text-ink-faint transition-colors hover:text-ink disabled:opacity-50"
              >
                {isResetting ? "Resetting…" : "Reset to default logo"}
              </button>
            )}
          </div>
        </div>
      </Card>

      <Card className="max-w-xl">
        <form onSubmit={handleSaveFooterYear} className="space-y-4">
          <h2 className="text-sm font-medium text-ink">Default footer copyright year</h2>
          <TextField
            label="Year"
            id="branding-footer-year"
            placeholder={new Date().getFullYear().toString()}
            value={footerYear}
            onChange={(e) => setFooterYear(e.target.value)}
            helperText="Used whenever a generation doesn't set its own footer year."
          />
          <Button type="submit" disabled={isSavingYear} variant="secondary">
            {isSavingYear ? "Saving…" : "Save"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
