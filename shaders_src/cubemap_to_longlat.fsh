
uniform lowp samplerCube s_Texture0;
varying highp vec2 v_TexCoord0;

const highp float PI = 3.1415927;

highp vec2 longLatFromWorldDir(highp vec3 dir)
{
	highp float longitude = atan(dir.x, dir.z);
	highp float latitude = -asin(dir.y);

	return vec2(clamp(longitude * (0.5 / PI)	  + 0.5, 0.0, 1.0),
				clamp(latitude * (0.5 / (PI*0.5)) + 0.5, 0.0, 1.0));
}

highp vec3 worldDirFromLongLat(highp vec2 long_lat)
{
	float xz = cos(long_lat.y);
	float y = sin(long_lat.y);
	
	vec3 dir = vec3(
		xz * cos(long_lat.x),
		y,
		xz * sin(long_lat.x)
		);

	return normalize(dir);
}

void main()
{
	highp vec3 R = worldDirFromLongLat(v_TexCoord0);

	R.xy = -R.xy;

	gl_FragColor = vec4(textureCube(s_Texture0, R).rgb, 1.0);
}
