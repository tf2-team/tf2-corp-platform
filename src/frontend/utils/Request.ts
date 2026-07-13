// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

interface IRequestParams {
  url: string;
  body?: object;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  queryParams?: Record<string, any>;
  headers?: Record<string, string>;
}

const request = async <T>({
  url = '',
  method = 'GET',
  body,
  queryParams = {},
  headers = {
    'content-type': 'application/json',
  },
}: IRequestParams): Promise<T> => {
  const response = await fetch(`${url}?${new URLSearchParams(queryParams).toString()}`, {
    method,
    body: body ? JSON.stringify(body) : undefined,
    headers,
  });

  const responseText = await response.text();

  if (!response.ok) {
    // API routes often return plain-text "Internal Server Error" on 500.
    // Surface a clear Error instead of letting JSON.parse throw SyntaxError.
    const snippet = responseText?.slice(0, 200) || response.statusText;
    throw new Error(`Request failed ${response.status} ${response.statusText}: ${snippet}`);
  }

  if (!responseText) {
    return undefined as unknown as T;
  }

  try {
    return JSON.parse(responseText) as T;
  } catch {
    throw new Error(`Invalid JSON response from ${url}: ${responseText.slice(0, 200)}`);
  }
};

export default request;
