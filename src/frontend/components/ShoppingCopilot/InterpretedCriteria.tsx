// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';

interface Props {
  criteria: string;
}

// Completely remove AI Analysis / AI Intent display per user request
export const InterpretedCriteria: React.FC<Props> = () => {
  return null;
};
