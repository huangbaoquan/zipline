#
# Copyright 2015 Quantopian, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from zipline.errors import (
    InvalidBenchmarkAsset,
    BenchmarkAssetNotAvailableTooEarly,
    BenchmarkAssetNotAvailableTooLate
)
from zipline.data.us_equity_pricing import NoDataOnDate


class BenchmarkSource(object):
    def __init__(self, benchmark_sid, env, trading_days, data_portal,
                 emission_rate="daily"):
        self.benchmark_sid = benchmark_sid
        self.env = env
        self.trading_days = trading_days
        self.emission_rate = emission_rate
        self.data_portal = data_portal

        if self.benchmark_sid:
            self.benchmark_asset = self.env.asset_finder.retrieve_asset(
                self.benchmark_sid)

            self._validate_benchmark()

        self.precalculated_series = \
            self._initialize_precalculated_series(
                self.benchmark_sid,
                self.env,
                self.trading_days,
                self.data_portal
            )

    def get_value(self, dt):
        return self.precalculated_series.loc[dt]

    def _validate_benchmark(self):
        # check if this security has a stock dividend.  if so, raise an
        # error suggesting that the user pick a different asset to use
        # as benchmark.
        stock_dividends = \
            self.data_portal.get_stock_dividends(self.benchmark_sid,
                                                 self.trading_days)

        if len(stock_dividends) > 0:
            raise InvalidBenchmarkAsset(
                sid=str(self.benchmark_sid),
                dt=stock_dividends[0]["ex_date"]
            )

        if self.benchmark_asset.start_date > self.trading_days[0]:
            # the asset started trading after the first simulation day
            raise BenchmarkAssetNotAvailableTooEarly(
                sid=str(self.benchmark_sid),
                dt=self.trading_days[0],
                start_dt=self.benchmark_asset.start_date
            )

        if self.benchmark_asset.end_date < self.trading_days[-1]:
            # the asset stopped trading before the last simulation day
            raise BenchmarkAssetNotAvailableTooLate(
                sid=str(self.benchmark_sid),
                dt=self.trading_days[0],
                end_dt=self.benchmark_asset.end_date
            )

    def _initialize_precalculated_series(self, sid, env, trading_days,
                                         data_portal):
        """
        Internal method that precalculates the benchmark return series for
        use in the simulation.

        Parameters
        ----------
        sid: (int) Asset to use

        env: TradingEnvironment

        trading_days: pd.DateTimeIndex

        data_portal: DataPortal

        Notes
        -----
        If the benchmark asset started trading after the simulation start,
        or finished trading before the simulation end, exceptions are raised.

        If the benchmark asset started trading the same day as the simulation
        start, the first available minute price on that day is used instead
        of the previous close.

        We use history to get an adjusted price history for each day's close,
        as of the look-back date (the last day of the simulation).  Prices are
        fully adjusted for dividends, splits, and mergers.

        Returns
        -------
        A pd.Series, indexed by trading day, whose values represent the %
        change from close to close.
        """
        if sid is None:
            # get benchmark info from trading environment, which defaults to
            # downloading data from Yahoo.
            daily_series = \
                env.benchmark_returns[trading_days[0]:trading_days[-1]]

            if self.emission_rate == "minute":
                # we need to take the env's benchmark returns, which are daily,
                # and resample them to minute
                minutes = env.minutes_for_days_in_range(
                    start=trading_days[0],
                    end=trading_days[-1]
                )

                minute_series = daily_series.reindex(
                    index=minutes,
                    method="ffill"
                )

                return minute_series
            else:
                return daily_series
        elif self.emission_rate == "minute":
            minutes = env.minutes_for_days_in_range(self.trading_days[0],
                                                    self.trading_days[-1])
            benchmark_series = data_portal.get_history_window(
                [sid],
                minutes[-1],
                bar_count=len(minutes) + 1,
                frequency="1m",
                field="price",
                ffill=True
            )

            return benchmark_series.pct_change()[1:]
        else:
            try:
                # get the window of close prices for benchmark_sid from the
                # last trading day of the simulation, going up to one day
                # before the simulation start day (so that we can get the %
                # change on day 1)
                benchmark_series = data_portal.get_history_window(
                    [sid],
                    trading_days[-1],
                    bar_count=len(trading_days) + 1,
                    frequency="1d",
                    field="price",
                    ffill=True
                )[sid]
                return benchmark_series.pct_change()[1:]
            except NoDataOnDate:
                # Attempt to handle case where stock data starts on first
                # day, in this case use the open to close return.
                benchmark_series = data_portal.get_history_window(
                    [sid],
                    trading_days[-1],
                    bar_count=len(trading_days),
                    frequency="1d",
                    field="price",
                    ffill=True
                )[sid]

                # get a minute history window of the first day
                first_open = data_portal.get_spot_value(
                    sid, 'open', trading_days[0])
                first_close = data_portal.get_spot_value(
                    sid, 'close', trading_days[0])

                first_day_return = (first_close - first_open) / first_open

                returns = benchmark_series.pct_change()[:]
                returns[0] = first_day_return
                return returns
