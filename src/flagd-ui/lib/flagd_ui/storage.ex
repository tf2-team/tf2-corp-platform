# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

defmodule FlagdUi.Storage do
  @moduledoc """
  Storage module. This module initializes a process as a separate GenServer
  to linearize reads and writes preventing conflicts and last-writer-wins.
  """

  use GenServer
  require Logger

  @file_path Application.compile_env!(:flagd_ui, :storage_file_path)

  def start_link(opts) do
    name = Keyword.get(opts, :name, Storage)

    GenServer.start_link(__MODULE__, %{}, name: name)
  end

  @impl true
  def init(_) do
    state = @file_path |> File.read!() |> Jason.decode!()
    Logger.info("Read new state from file")

    {:ok, state}
  end

  @impl true
  def handle_call(:read, _from, state) do
    {:reply, state, state}
  end

  @impl true
  def handle_cast({:replace, json_string}, _) do
    new_state = Jason.decode!(json_string)

    write_state(json_string)

    {:noreply, new_state}
  end

  @impl true
  def handle_cast({:write, flag_name, flag_value}, state) do
    new_state =
      Map.update(state, "flags", %{}, fn flags ->
        update_flag(flags, flag_name, flag_value)
      end)

    json_state = Jason.encode!(new_state, pretty: true)

    write_state(json_state)

    {:noreply, new_state}
  end

  defp update_flag(flags, flag_name, value) do
    flags
    |> Enum.map(fn
      {flag, data} when flag == flag_name -> {flag, Map.replace(data, "defaultVariant", value)}
      {flag, data} -> {flag, data}
    end)
    |> Map.new()
  end

  defp write_state(json_string) do
    # flagd watches this path with fsnotify. Writing it in place briefly
    # truncates the file, so flagd can read an empty JSON document and discard
    # the update. A same-directory rename exposes only the complete document.
    temp_path = "#{@file_path}.tmp"

    File.write!(temp_path, json_string)
    File.rename!(temp_path, @file_path)

    Logger.info("Wrote new state to file")
  end
end
