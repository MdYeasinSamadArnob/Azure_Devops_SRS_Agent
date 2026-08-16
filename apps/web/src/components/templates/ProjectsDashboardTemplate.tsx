"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Card } from "@/components/atoms/Card";
import { Skeleton } from "@/components/atoms/Skeleton";
import { AzureConnectionForm } from "@/components/organisms/AzureConnectionForm";
import { apiClient } from "@/lib/api-client";

interface ProjectListItem {
  id: string;
  name: string;
  azure_org: string;
  azure_project: string;
  created_at: string;
  updated_at: string;
}

export function ProjectsDashboardTemplate() {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [showNewProjectForm, setShowNewProjectForm] = useState(false);

  useEffect(() => {
    apiClient
      .get<ProjectListItem[]>("/projects")
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  if (showNewProjectForm || (projects !== null && projects.length === 0)) {
    return (
      <div className="animate-fade-up space-y-8">
        <div className="space-y-3">
          {projects !== null && projects.length > 0 && (
            <button
              type="button"
              onClick={() => setShowNewProjectForm(false)}
              className="text-xs font-medium text-ink-faint transition-colors hover:text-ink"
            >
              ← Back to projects
            </button>
          )}
          <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">
            Step 1 — Import
          </span>
          <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-4xl">
            Bring in a backlog.
          </h1>
          <p className="max-w-lg text-[15px] leading-relaxed text-ink-muted">
            Paste an Azure DevOps backlog or work-item URL to discover its Epic → Feature → Story →
            Task/Bug hierarchy, then choose exactly what belongs in your SRS.
          </p>
        </div>
        <AzureConnectionForm />
      </div>
    );
  }

  return (
    <div className="animate-fade-up space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-3">
          <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">Your projects</span>
          <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-4xl">Projects</h1>
        </div>
        <Button onClick={() => setShowNewProjectForm(true)}>+ New project</Button>
      </div>

      {projects === null ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <Link key={project.id} href={`/projects/${project.id}/generations`}>
              <Card className="transition-colors hover:border-accent/40">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{project.name}</p>
                    <p className="mt-0.5 font-mono text-[11px] text-ink-faint">
                      {project.azure_org}/{project.azure_project}
                    </p>
                  </div>
                  <Badge tone="neutral">{new Date(project.updated_at).toLocaleDateString()}</Badge>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
