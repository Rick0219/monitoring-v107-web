import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

/** Keep vertical scrolling with the surrounding page or dialog, never the table. */
export function PageScrollTable({
  children,
  label = "数据库表格",
}: {
  children: ReactNode;
  label?: string;
}) {
  const frame = useRef<HTMLDivElement>(null),
    surface = useRef<HTMLDivElement>(null),
    horizontal = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ table: 0, viewport: 0, top: 0 });
  const wide = size.table > size.viewport + 1;
  function syncHorizontal() {
    frame.current?.style.setProperty(
      "--database-scroll-x",
      `${-(horizontal.current?.scrollLeft || 0)}px`,
    );
  }
  useLayoutEffect(() => {
    const viewport = surface.current!,
      table = viewport.querySelector("table")!;
    const dialog = viewport.closest(".modal");
    const topbar = dialog
      ? null
      : viewport.closest(".main")?.querySelector(".topbar");
    const measure = () => {
      const style = topbar && getComputedStyle(topbar);
      const top = dialog
        ? -(parseFloat(getComputedStyle(dialog).paddingTop) || 0)
        : topbar && style && ["fixed", "sticky"].includes(style.position)
          ? topbar.getBoundingClientRect().height + (parseFloat(style.top) || 0)
          : 0;
      const next = {
        table: table.getBoundingClientRect().width,
        viewport: viewport.clientWidth,
        top,
      };
      setSize((previous) =>
        Object.keys(next).every(
          (key) =>
            previous[key as keyof typeof next] ===
            next[key as keyof typeof next],
        )
          ? previous
          : next,
      );
      if (next.table <= next.viewport + 1 && horizontal.current)
        horizontal.current.scrollLeft = 0;
      syncHorizontal();
    };
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    observer.observe(table);
    if (dialog) observer.observe(dialog);
    if (topbar) observer.observe(topbar);
    window.addEventListener("resize", measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  return (
    <div
      className="database-table-frame"
      ref={frame}
      style={
        {
          "--database-header-offset": `${size.top}px`,
          "--database-horizontal-height": wide ? "20px" : "0px",
        } as CSSProperties
      }
    >
      <div
        ref={horizontal}
        className="database-horizontal-scroll"
        hidden={!wide}
        role="region"
        aria-label={`${label}横向滚动`}
        title="左右滚动可查看其余列"
        tabIndex={0}
        onScroll={syncHorizontal}
      >
        <div style={{ width: size.table, height: 1 }} />
      </div>
      <div
        ref={surface}
        className="database-table-surface"
        tabIndex={0}
        role="region"
        aria-label={label}
        onFocusCapture={(event) => {
          // Tab navigation into an off-screen input must also reveal its column.
          if (event.target === event.currentTarget || !horizontal.current)
            return;
          const viewport = event.currentTarget.getBoundingClientRect();
          const target = event.target.getBoundingClientRect();
          const shift =
            target.left < viewport.left
              ? target.left - viewport.left
              : target.right > viewport.right
                ? Math.min(
                    target.right - viewport.right,
                    target.left - viewport.left,
                  )
                : 0;
          if (shift) {
            horizontal.current.scrollLeft += shift;
            syncHorizontal();
          }
        }}
        onWheel={(event) => {
          // Horizontal trackpad gestures move columns; never intercept vertical scrolling.
          if (horizontal.current && event.deltaX)
            horizontal.current.scrollLeft += event.deltaX;
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget || !horizontal.current)
            return;
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            horizontal.current.scrollLeft +=
              event.key === "ArrowLeft" ? -80 : 80;
          }
        }}
      >
        {children}
      </div>
    </div>
  );
}
