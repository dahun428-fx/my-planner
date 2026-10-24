import styles from "./Skeleton.module.css";

export type SkeletonSize = "line" | "short" | "title" | "pill" | "row";

// Grey placeholder at the real size of the value it stands for (spec 5.4). No shimmer.
export function Skeleton({ size }: { size: SkeletonSize }) {
  return <span className={`${styles.skeleton} ${styles[size]}`} aria-hidden="true" />;
}
