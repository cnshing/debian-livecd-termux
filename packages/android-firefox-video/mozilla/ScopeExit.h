// Standalone RAII guard for Mozilla's otherwise self-contained graphics probe.
#pragma once
#include <utility>
namespace mozilla {
template<class F> class ExitGuard {
  F f;
public:
  explicit ExitGuard(F fn) : f(std::move(fn)) {}
  ExitGuard(const ExitGuard&) = delete;
  ~ExitGuard() { f(); }
};
template<class F> auto MakeScopeExit(F f) { return ExitGuard<F>(std::move(f)); }
}
