// Metro bundles CSS imported for its side effects (MapLibre ships its own
// stylesheet, and the map's controls are unusable without it). TypeScript 6
// rejects such an import unless the module is declared.
declare module '*.css';
