import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Feature } from "@/api/types";

/** One shape out of several (phase 33, decision D274): how many pieces it lies in decides
 * whether the drawing editor can take it. */
export interface CombinedArea {
  geometry: GeoJSON.Geometry;
  area_m2: number;
  parts: number;
}

/** Joins areas without storing anything: the project's own features, shapes that are not
 * saved yet (a proposal's candidates), or both, so the result is seen before it is kept. */
export function useUnionAreas(projectId: string) {
  return useMutation({
    mutationFn: (ask: {
      geometries?: GeoJSON.Geometry[];
      featureIds?: string[];
    }) =>
      api.post<CombinedArea>(`/api/v1/projects/${projectId}/features/union`, {
        body: {
          geometries: ask.geometries ?? [],
          feature_ids: ask.featureIds ?? [],
        },
      }),
  });
}

/** Saves several of the project's features as one new feature, in one request: the parts are
 * kept unless they are asked to go with it. */
export function useCombineFeatures(projectId: string) {
  return useMutation({
    mutationFn: (values: {
      name: string;
      feature_type: string;
      feature_ids: string[];
      remove_parts: boolean;
    }) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features/combine`, {
        body: values,
      }),
  });
}
